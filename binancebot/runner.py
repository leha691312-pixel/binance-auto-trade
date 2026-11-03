import os
import time

from .client import BinanceError
from .risk import Rules, check, fmt, size_position
from .strategy import prepare, signal_at, warmup

_rules = {}


def log(msg):
    print(time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime()), "UTC |", msg, flush=True)


def get_rules(client, symbol):
    if symbol not in _rules:
        _rules[symbol] = Rules.from_info(client.exchange_info(symbol))
    return _rules[symbol]


def closed_candles(raw, now_ms):
    return [c for c in raw if c.ct < now_ms]


def equity_of(broker, store):
    return broker.free_quote() + sum(p["qty"] * p["entry"] for p in store.data["positions"])


def scan_symbol(cfg, client, broker, store, symbol, now_ms, confirm):
    candles = closed_candles(client.klines(symbol, cfg["interval"], 300), now_ms)
    if len(candles) < warmup(cfg) + 2:
        return
    last = candles[-1]
    if store.data["seen"].get(symbol) == last.t:          # one decision per closed candle
        return
    store.data["seen"][symbol] = last.t
    sig = signal_at(symbol, candles, prepare(candles, cfg), len(candles) - 1, cfg)
    if not sig:
        return
    rules = get_rules(client, symbol)
    free = broker.free_quote()
    qty, note = size_position(sig.entry, sig.stop, equity_of(broker, store), free, cfg, rules)
    blocks = check(sig, qty, store.data["positions"], store.stats(now_ms), cfg,
                   os.path.exists(cfg["kill_file"]))
    if note != "ok":
        blocks.append(note)
    msg = "%s signal @ %.6g stop %.6g target %.6g qty %s" % (symbol, sig.entry, sig.stop, sig.target, fmt(qty))
    if blocks:
        log("BLOCK " + msg + " | " + "; ".join(blocks))
        return
    if confirm and not confirm(sig, qty):
        log("DECLINED " + msg)
        return
    pos = broker.buy(sig, rules, qty, now_ms)
    store.data["positions"].append(pos)
    log("BUY " + msg + " | mode=%s id=%s" % (pos["mode"], pos["id"]))


def run_once(cfg, client, broker, store, confirm=None):
    now_ms = int(time.time() * 1000)
    for t in broker.sync(store.data["positions"], now_ms):
        store.close(t)
        log("CLOSED %s %s exit %.6g pnl %+.2f (%.2fR)" % (t["symbol"], t["reason"], t["exit"], t["pnl"], t["r"]))
    store.save()
    if os.path.exists(cfg["kill_file"]):
        log("KILL file present: managing exits only, no new entries")
        return
    for symbol in cfg["symbols"]:
        try:
            scan_symbol(cfg, client, broker, store, symbol, now_ms, confirm)
        except BinanceError as e:
            log("ERROR %s: %s" % (symbol, e))
        store.save()
