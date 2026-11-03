"""Position sizing, exchange-rule rounding and pre-trade risk checks."""
from dataclasses import dataclass
from decimal import Decimal


def d(x):
    return Decimal(str(x))


def floor_step(x, step):
    step = d(step)
    if step == 0:
        return d(x)
    return (d(x) // step) * step


def fmt(x):
    return format(d(x).normalize(), "f")


@dataclass
class Rules:
    symbol: str
    base: str
    quote: str
    step: Decimal
    min_qty: Decimal
    tick: Decimal
    min_notional: Decimal

    @classmethod
    def from_info(cls, info):
        f = {x["filterType"]: x for x in info["filters"]}
        notional = f.get("NOTIONAL") or f.get("MIN_NOTIONAL") or {}
        return cls(info["symbol"], info["baseAsset"], info["quoteAsset"],
                   d(f["LOT_SIZE"]["stepSize"]), d(f["LOT_SIZE"]["minQty"]),
                   d(f["PRICE_FILTER"]["tickSize"]), d(notional.get("minNotional", 0)))

    def price(self, p):
        return floor_step(p, self.tick)


def size_position(entry, stop, equity, free_quote, cfg, rules):
    """Quantity whose loss at the stop (fees included) <= max loss, capped by
    position-size % and by available cash. Returns (Decimal qty, note)."""
    if stop >= entry:
        return Decimal(0), "stop must be below entry"
    fee = cfg["fee_pct"] / 100.0
    risk_per_unit = (entry - stop) + fee * (entry + stop)
    q = min(cfg["max_loss_per_trade_usd"] / risk_per_unit,
            cfg["max_position_pct"] / 100.0 * equity / entry,
            free_quote * 0.995 / (entry * (1 + fee)))
    qty = floor_step(q, rules.step)
    if qty < rules.min_qty:
        return Decimal(0), "size %s below min qty %s" % (qty, rules.min_qty)
    if qty * d(entry) < rules.min_notional:
        return Decimal(0), "notional %.2f below minimum %s" % (float(qty) * entry, rules.min_notional)
    return qty, "ok"


def check(sig, qty, positions, stats, cfg, killed):
    """List of reasons to BLOCK the trade. Empty list = PASS."""
    why = []
    if killed:
        why.append("kill switch file present")
    if stats["daily_loss"] >= cfg["daily_loss_limit_usd"]:
        why.append("daily loss limit reached (%.2f)" % stats["daily_loss"])
    if stats["trades_today"] >= cfg["max_trades_per_day"]:
        why.append("max trades per day reached")
    if len(positions) >= cfg["max_open_positions"]:
        why.append("max open positions reached")
    if any(p["symbol"] == sig.symbol for p in positions):
        why.append("already in %s" % sig.symbol)
    risk = sig.entry - sig.stop
    if risk <= 0 or (sig.target - sig.entry) / risk < cfg["min_reward_risk"]:
        why.append("reward/risk below minimum")
    stop_pct = risk / sig.entry * 100.0
    if not (cfg["min_stop_pct"] <= stop_pct <= cfg["max_stop_pct"]):
        why.append("stop distance %.2f%% outside [%.2f, %.2f]" % (
            stop_pct, cfg["min_stop_pct"], cfg["max_stop_pct"]))
    if qty <= 0:
        why.append("quantity is zero")
    return why
