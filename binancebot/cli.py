import argparse
import os
import sys
import time

from . import config as config_mod
from .backtest import backtest
from .broker import BinanceBroker, PaperBroker
from .client import URLS, Client
from .runner import log, run_once
from .store import Store
from .strategy import prepare, signal_at

LIVE_PHRASE = "I_ACCEPT_THE_RISK"


def build(cfg):
    mode = cfg["mode"]
    if mode == "live" and os.environ.get("BINANCE_LIVE_CONFIRM") != LIVE_PHRASE:
        sys.exit("Refusing to trade live. Set BINANCE_LIVE_CONFIRM=%s if you really mean it." % LIVE_PHRASE)
    client = Client(cfg["base_url"] or URLS[mode], os.environ.get("BINANCE_API_KEY", ""),
                    os.environ.get("BINANCE_API_SECRET", ""))
    store = Store(cfg["state_file"], cfg["account_equity"])
    broker = PaperBroker(client, cfg, store) if mode == "paper" else BinanceBroker(client, cfg, mode)
    return client, store, broker


def ask_yes(sig, qty):
    ans = input("BUY %s qty %s @ ~%.6g stop %.6g target %.6g ? type yes: " % (
        sig.symbol, qty, sig.entry, sig.stop, sig.target))
    return ans.strip().lower() == "yes"


def cmd_scan(cfg, args):
    client, _, _ = build(cfg)
    now = int(time.time() * 1000)
    for s in cfg["symbols"]:
        cs = [c for c in client.klines(s, cfg["interval"], 300) if c.ct < now]
        sig = signal_at(s, cs, prepare(cs, cfg), len(cs) - 1, cfg)
        print("%-10s %s" % (s, "SETUP entry %.6g stop %.6g target %.6g rsi %.1f" % (
            sig.entry, sig.stop, sig.target, sig.rsi) if sig else "no setup"))


def cmd_backtest(cfg, args):
    client = Client(cfg["base_url"] or URLS["paper"])
    cs = client.klines_paged(args.symbol, args.interval or cfg["interval"], args.candles)
    res = backtest(cs, cfg, args.symbol)
    print("%s %s, %d candles" % (args.symbol, args.interval or cfg["interval"], len(cs)))
    for k, v in res.items():
        print("  %-18s %s" % (k, ("%.2f" % v) if isinstance(v, float) else v))
    print("Past results do not predict future results. Fees and slippage are estimates.")


def cmd_run(cfg, args):
    client, store, broker = build(cfg)
    confirm = ask_yes if (cfg["mode"] == "live" and cfg["require_confirm"]) else None
    log("mode=%s symbols=%s interval=%s" % (cfg["mode"], ",".join(cfg["symbols"]), cfg["interval"]))
    while True:
        try:
            run_once(cfg, client, broker, store, confirm)
        except Exception as e:  # keep the loop alive, never crash into an unmanaged position
            log("ERROR %s: %s" % (type(e).__name__, e))
        if args.once:
            return
        time.sleep(cfg["poll_seconds"])


def cmd_status(cfg, args):
    store = Store(cfg["state_file"], cfg["account_equity"])
    st = store.stats()
    print("mode=%s  paper cash=%.2f" % (cfg["mode"], store.data["paper_cash"]))
    print("today: pnl %+.2f, trades %d (limits: loss %.0f, trades %d)" % (
        st["daily_pnl"], st["trades_today"], cfg["daily_loss_limit_usd"], cfg["max_trades_per_day"]))
    for p in store.data["positions"]:
        print("OPEN   %-9s qty %.6g entry %.6g stop %.6g target %.6g" % (
            p["symbol"], p["qty"], p["entry"], p["stop"], p["target"]))
    for t in store.data["closed"][-10:]:
        print("CLOSED %-9s %-6s pnl %+.2f (%.2fR)" % (t["symbol"], t["reason"], t["pnl"], t["r"]))
    total = sum(t["pnl"] for t in store.data["closed"])
    print("all-time realized pnl %+.2f over %d trades" % (total, len(store.data["closed"])))


def cmd_halt(cfg, args):
    open(cfg["kill_file"], "w").close()
    print("kill switch ON: no new entries (exits keep being managed)")


def cmd_resume(cfg, args):
    if os.path.exists(cfg["kill_file"]):
        os.remove(cfg["kill_file"])
    print("kill switch OFF")


def main(argv=None):
    p = argparse.ArgumentParser(prog="binancebot", description="Binance spot auto-trade bot (paper by default)")
    p.add_argument("--config", help="path to config json (default: ./config.json if present)")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("scan", help="show current setups, places no orders").set_defaults(fn=cmd_scan)
    b = sub.add_parser("backtest", help="replay the strategy on history")
    b.add_argument("--symbol", default="BTCUSDT")
    b.add_argument("--interval")
    b.add_argument("--candles", type=int, default=3000)
    b.set_defaults(fn=cmd_backtest)
    r = sub.add_parser("run", help="run the bot loop")
    r.add_argument("--once", action="store_true", help="single pass then exit")
    r.set_defaults(fn=cmd_run)
    sub.add_parser("status", help="positions and PnL").set_defaults(fn=cmd_status)
    sub.add_parser("halt", help="kill switch: stop new entries").set_defaults(fn=cmd_halt)
    sub.add_parser("resume", help="remove kill switch").set_defaults(fn=cmd_resume)
    args = p.parse_args(argv)
    args.fn(config_mod.load(args.config), args)


if __name__ == "__main__":
    main()
