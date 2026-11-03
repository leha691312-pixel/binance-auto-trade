"""Brokers. PaperBroker simulates fills on real candles; BinanceBroker sends
real orders (testnet or live): market buy, then an OCO sell (take profit + stop)."""
import uuid

from .client import BinanceError
from .risk import floor_step, fmt


def new_position(sig, symbol, qty, fill, stop, target, now_ms, mode, **extra):
    pos = {"id": uuid.uuid4().hex[:8], "symbol": symbol, "qty": float(qty), "entry": fill,
           "stop": stop, "target": target, "opened_at": now_ms, "mode": mode,
           "risk_usd": float(qty) * (fill - stop), "checked_ms": now_ms}
    pos.update(extra)
    return pos


def close_trade(pos, exit_price, reason, now_ms, fee_pct):
    fee = fee_pct / 100.0
    q = pos["qty"]
    pnl = q * (exit_price - pos["entry"]) - fee * q * (pos["entry"] + exit_price)
    t = dict(pos)
    t.update(exit=exit_price, reason=reason, closed_at=now_ms, pnl=pnl,
             r=pnl / pos["risk_usd"] if pos["risk_usd"] else 0.0)
    return t


class PaperBroker:
    mode = "paper"

    def __init__(self, client, cfg, store):
        self.client, self.cfg, self.store = client, cfg, store

    def free_quote(self):
        return self.store.data["paper_cash"]

    def buy(self, sig, rules, qty, now_ms):
        slip, fee = self.cfg["slippage_pct"] / 100.0, self.cfg["fee_pct"] / 100.0
        fill = sig.entry * (1 + slip)
        risk = sig.entry - sig.stop
        stop, target = fill - risk, fill + self.cfg["reward_risk"] * risk
        self.store.data["paper_cash"] -= float(qty) * fill * (1 + fee)
        return new_position(sig, sig.symbol, qty, fill, stop, target, now_ms, "paper")

    def sync(self, positions, now_ms):
        closed, slip = [], self.cfg["slippage_pct"] / 100.0
        for pos in list(positions):
            try:
                bars = [c for c in self.client.klines(pos["symbol"], "1m", 1000, start=pos["checked_ms"] + 1)
                        if c.ct < now_ms]
            except BinanceError as e:
                print("  sync %s failed: %s" % (pos["symbol"], e))
                continue
            exit_price = reason = None
            for c in bars:
                if c.l <= pos["stop"]:                      # stop first when both hit
                    exit_price, reason = min(pos["stop"], c.o) * (1 - slip), "stop"
                    break
                if c.h >= pos["target"]:
                    exit_price, reason = pos["target"], "target"
                    break
            if bars:
                pos["checked_ms"] = bars[-1].ct
            if reason is None and now_ms - pos["opened_at"] > self.cfg["max_hold_hours"] * 3600000 and bars:
                exit_price, reason = bars[-1].c * (1 - slip), "time"
            if reason:
                t = close_trade(pos, exit_price, reason, now_ms, self.cfg["fee_pct"])
                self.store.data["paper_cash"] += pos["qty"] * exit_price * (1 - self.cfg["fee_pct"] / 100.0)
                closed.append(t)
        return closed


class BinanceBroker:
    def __init__(self, client, cfg, mode):
        self.client, self.cfg, self.mode = client, cfg, mode

    def free_quote(self):
        return self.client.balances().get(self.cfg["quote_asset"], 0.0)

    def buy(self, sig, rules, qty, now_ms):
        res = self.client.market_buy(sig.symbol, fmt(qty))
        got, spent = float(res["executedQty"]), float(res["cummulativeQuoteQty"])
        if got <= 0:
            raise BinanceError("market buy not filled")
        fill = spent / got
        base_fee = sum(float(f["commission"]) for f in res.get("fills", [])
                       if f.get("commissionAsset") == rules.base)
        sell_qty = floor_step(got - base_fee, rules.step)       # fee in base asset shrinks the balance
        risk = sig.entry - sig.stop
        stop = rules.price(fill - risk)
        target = rules.price(fill + self.cfg["reward_risk"] * risk)
        stop_limit = rules.price(stop * 0.998)
        try:
            oco = self.client.oco_sell(sig.symbol, fmt(sell_qty), fmt(target), fmt(stop), fmt(stop_limit))
        except BinanceError:
            self.client.market_sell(sig.symbol, fmt(sell_qty))  # never stay in a trade without a stop
            raise
        return new_position(sig, sig.symbol, sell_qty, fill, float(stop), float(target), now_ms,
                            self.mode, oco_list_id=oco["orderListId"])

    def _exit_from_fills(self, res):
        return float(res["cummulativeQuoteQty"]) / float(res["executedQty"])

    def sync(self, positions, now_ms):
        closed = []
        for pos in list(positions):
            try:
                ol = self.client.order_list(pos["oco_list_id"])
                exit_price = reason = None
                if ol["listOrderStatus"] == "ALL_DONE":
                    for o in ol["orders"]:
                        od = self.client.order(pos["symbol"], o["orderId"])
                        if od["status"] == "FILLED":
                            exit_price = float(od["cummulativeQuoteQty"]) / float(od["executedQty"])
                            reason = "target" if od["type"] == "LIMIT_MAKER" else "stop"
                    if reason is None:
                        exit_price, reason = pos["entry"], "oco_cancelled_outside_bot"
                elif now_ms - pos["opened_at"] > self.cfg["max_hold_hours"] * 3600000:
                    self.client.cancel_order_list(pos["symbol"], pos["oco_list_id"])
                    res = self.client.market_sell(pos["symbol"], fmt(pos["qty"]))
                    exit_price, reason = self._exit_from_fills(res), "time"
                if reason:
                    closed.append(close_trade(pos, exit_price, reason, now_ms, self.cfg["fee_pct"]))
            except (BinanceError, KeyError, ValueError, ZeroDivisionError) as e:
                print("  sync %s failed: %s" % (pos["symbol"], e))
        return closed
