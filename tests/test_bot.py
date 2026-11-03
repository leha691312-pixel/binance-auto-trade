import os
import random
import sys
import tempfile
import unittest
from decimal import Decimal

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from binancebot import config as config_mod
from binancebot.backtest import backtest
from binancebot.broker import PaperBroker
from binancebot.client import Candle, sign
from binancebot.indicators import atr, ema, rsi
from binancebot.risk import Rules, check, floor_step, fmt, size_position
from binancebot.store import Store
from binancebot.strategy import Signal, prepare, signal_at

CFG = config_mod.load()
RULES = Rules("TESTUSDT", "TEST", "USDT", Decimal("0.01"), Decimal("0.01"), Decimal("0.01"), Decimal("5"))


def make(n, seed=1, drift=0.0006, vol=0.004):
    rnd, p, out = random.Random(seed), 100.0, []
    for i in range(n):
        o = p
        c = o * (1 + drift + rnd.gauss(0, vol))
        h = max(o, c) * (1 + abs(rnd.gauss(0, 0.001)))
        l = min(o, c) * (1 - abs(rnd.gauss(0, 0.001)))
        out.append(Candle(i * 900000, o, h, l, c, 100 + rnd.random() * 20, i * 900000 + 899999))
        p = c
    return out


def sig(entry=100.0, stop=98.0, target=104.0, symbol="TESTUSDT"):
    return Signal(symbol, 0, 0, entry, stop, target, 1.0, 60.0, "breakout")


class FakeClient:
    def __init__(self, bars):
        self.bars = bars

    def klines(self, symbol, interval, limit=500, start=None, end=None):
        return [b for b in self.bars if start is None or b.t >= start]


class Tests(unittest.TestCase):
    def test_signature_matches_binance_docs_vector(self):
        secret = "NhqPtmdSJYdKjVHjA7PZj4Mge3R5YNiP1e3UZjInClVN65XAbvqqM6A7H5fATj0j"
        q = ("symbol=LTCBTC&side=BUY&type=LIMIT&timeInForce=GTC&quantity=1"
             "&price=0.1&recvWindow=5000&timestamp=1499827319559")
        self.assertEqual(sign(secret, q), "c8db56825ae71d6d79447849e617115f4a920fa2acdcab2b053c4b2838bd6b71")

    def test_indicators(self):
        self.assertAlmostEqual(ema([5.0] * 30, 10)[-1], 5.0)
        up = rsi([float(i) for i in range(40)], 14)[-1]
        self.assertEqual(up, 100.0)
        cs = make(100)
        a = atr([c.h for c in cs], [c.l for c in cs], [c.c for c in cs], 14)[-1]
        self.assertTrue(0 < a < 5)

    def test_rounding(self):
        self.assertEqual(floor_step(1.2399, "0.01"), Decimal("1.23"))
        self.assertEqual(fmt(Decimal("1.2300")), "1.23")
        self.assertEqual(fmt(Decimal("10")), "10")

    def test_size_respects_max_loss_and_cap(self):
        qty, note = size_position(100.0, 98.0, 1000.0, 1000.0, CFG, RULES)
        self.assertEqual(note, "ok")
        loss = float(qty) * (2.0 + 0.001 * 198.0)
        self.assertLessEqual(loss, CFG["max_loss_per_trade_usd"] + 1e-9)
        self.assertLessEqual(float(qty) * 100.0, 250.0 + 1e-9)

    def test_size_blocks_tiny_notional(self):
        qty, note = size_position(100.0, 98.0, 1000.0, 3.0, CFG, RULES)
        self.assertEqual(qty, 0)
        self.assertNotEqual(note, "ok")

    def test_risk_checks(self):
        ok = {"daily_loss": 0.0, "trades_today": 0}
        self.assertEqual(check(sig(), Decimal(1), [], ok, CFG, False), [])
        self.assertTrue(check(sig(), Decimal(1), [], ok, CFG, True))
        self.assertTrue(check(sig(), Decimal(1), [], {"daily_loss": 31.0, "trades_today": 0}, CFG, False))
        self.assertTrue(check(sig(), Decimal(1), [], {"daily_loss": 0.0, "trades_today": 5}, CFG, False))
        self.assertTrue(check(sig(), Decimal(1), [{"symbol": "TESTUSDT"}], ok, CFG, False))
        self.assertTrue(check(sig(target=101.0), Decimal(1), [], ok, CFG, False))     # reward/risk too low
        self.assertTrue(check(sig(stop=80.0, target=140.0), Decimal(1), [], ok, CFG, False))  # stop too wide
        self.assertTrue(check(sig(), Decimal(0), [], ok, CFG, False))

    def test_breakout_signal(self):
        cfg = dict(CFG, rsi_max=100)
        cs = make(120, drift=0.001, vol=0.003)
        last = cs[-1]
        jump = last.c * 1.03
        cs.append(Candle(last.t + 900000, last.c, jump * 1.001, last.c, jump, 500.0, last.ct + 900000))
        s = signal_at("X", cs, prepare(cs, cfg), len(cs) - 1, cfg)
        self.assertIsNotNone(s)
        self.assertLess(s.stop, s.entry)
        self.assertGreater(s.target, s.entry)
        self.assertAlmostEqual((s.target - s.entry) / (s.entry - s.stop), cfg["reward_risk"])

    def test_no_signal_in_downtrend(self):
        cs = make(200, drift=-0.001)
        ind = prepare(cs, CFG)
        self.assertTrue(all(signal_at("X", cs, ind, i, CFG) is None for i in range(len(cs))))

    def test_backtest_runs_and_is_consistent(self):
        cfg = dict(CFG, rsi_max=100, volume_mult=0.0)   # synthetic volume is flat noise
        res = backtest(make(1500, seed=3, drift=0.0004), cfg)
        self.assertGreater(res["trades"], 0)
        self.assertEqual(sum(res["exits"].values()), res["trades"])
        self.assertGreaterEqual(res["max_drawdown_pct"], 0.0)

    def _paper(self, bars):
        d = tempfile.mkdtemp()
        store = Store(os.path.join(d, "s.json"), 1000.0)
        broker = PaperBroker(FakeClient(bars), CFG, store)
        pos = broker.buy(sig(), RULES, Decimal("2"), 1000)
        return broker, store, pos

    def test_paper_target_and_stop(self):
        now = 10 * 3600000
        win = [Candle(60000, 100, 101, 99.5, 100.5, 1, 119999), Candle(120000, 100.5, pos_t(), 100, 104, 1, 179999)]
        broker, store, pos = self._paper(win)
        out = broker.sync([pos], now)
        self.assertEqual(out[0]["reason"], "target")
        self.assertGreater(out[0]["pnl"], 0)

        both = [Candle(60000, 100, 200, 1, 100, 1, 119999)]       # hits both -> stop wins
        broker, store, pos = self._paper(both)
        out = broker.sync([pos], now)
        self.assertEqual(out[0]["reason"], "stop")
        self.assertLess(out[0]["pnl"], 0)
        self.assertLess(out[0]["r"], 0)

    def test_store_daily_stats(self):
        d = tempfile.mkdtemp()
        st = Store(os.path.join(d, "s.json"), 1000.0)
        now = 5 * 86400000 + 3600000
        st.data["closed"].append({"id": "a", "opened_at": now - 1000, "closed_at": now - 500, "pnl": -12.0})
        st.data["closed"].append({"id": "b", "opened_at": 0, "closed_at": 1000, "pnl": -99.0})
        s = st.stats(now)
        self.assertEqual(s["daily_loss"], 12.0)
        self.assertEqual(s["trades_today"], 1)
        st.save()
        self.assertEqual(Store(st.path, 1.0).data["closed"][0]["id"], "a")

    def test_config_rejects_unknown_keys(self):
        d = tempfile.mkdtemp()
        p = os.path.join(d, "c.json")
        with open(p, "w") as f:
            f.write('{"mode": "paper", "typo_key": 1}')
        with self.assertRaises(ValueError):
            config_mod.load(p)

    def test_run_once_end_to_end_paper(self):
        import time
        from binancebot import runner
        runner._rules.clear()
        cfg = dict(CFG, rsi_max=100, symbols=["TESTUSDT"], kill_file=os.path.join(tempfile.mkdtemp(), "KILL"))
        cs = make(120, drift=0.001, vol=0.003)
        last = cs[-1]
        jump = last.c * 1.03
        cs.append(Candle(last.t + 900000, last.c, jump * 1.001, last.c, jump, 500.0, last.ct + 900000))
        shift = int(time.time() * 1000) - 3600000 - cs[-1].ct          # all candles closed, ~1h ago
        cs = [Candle(c.t + shift, c.o, c.h, c.l, c.c, c.v, c.ct + shift) for c in cs]

        class C(FakeClient):
            def klines(self, symbol, interval, limit=500, start=None, end=None):
                if interval == "1m":
                    return []
                return self.bars

            def exchange_info(self, symbol):
                return {"symbol": symbol, "baseAsset": "TEST", "quoteAsset": "USDT", "filters": [
                    {"filterType": "LOT_SIZE", "stepSize": "0.001", "minQty": "0.001"},
                    {"filterType": "PRICE_FILTER", "tickSize": "0.01"},
                    {"filterType": "NOTIONAL", "minNotional": "5"}]}

        client = C(cs)
        store = Store(os.path.join(tempfile.mkdtemp(), "s.json"), 1000.0)
        broker = PaperBroker(client, cfg, store)
        runner.run_once(cfg, client, broker, store)
        self.assertEqual(len(store.data["positions"]), 1)
        pos = store.data["positions"][0]
        self.assertLessEqual(pos["risk_usd"], cfg["max_loss_per_trade_usd"] * 1.0001)
        self.assertLess(store.data["paper_cash"], 1000.0)
        runner.run_once(cfg, client, broker, store)                       # same candle: no second entry
        self.assertEqual(len(store.data["positions"]), 1)
        open(cfg["kill_file"], "w").close()
        store.data["seen"].clear()
        store.data["positions"].clear()
        runner.run_once(cfg, client, broker, store)                       # kill switch blocks entries
        self.assertEqual(len(store.data["positions"]), 0)


def pos_t():
    return 105.0


if __name__ == "__main__":
    unittest.main()
