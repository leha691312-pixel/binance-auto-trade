"""Trend breakout: close above the N-bar high, in an uptrend, with volume.
Long only. Stop = ATR multiple below entry, target = reward_risk x risk."""
from dataclasses import dataclass

from .indicators import atr, ema, rsi, sma


@dataclass
class Signal:
    symbol: str
    index: int
    candle_t: int
    entry: float
    stop: float
    target: float
    atr: float
    rsi: float
    reason: str


def warmup(cfg):
    return max(cfg["ema_slow"], cfg["breakout_lookback"], cfg["rsi_period"],
               cfg["atr_period"], cfg["volume_ma"]) + 1


def prepare(candles, cfg):
    c = [x.c for x in candles]
    return {
        "ema_f": ema(c, cfg["ema_fast"]),
        "ema_s": ema(c, cfg["ema_slow"]),
        "rsi": rsi(c, cfg["rsi_period"]),
        "atr": atr([x.h for x in candles], [x.l for x in candles], c, cfg["atr_period"]),
        "vol_ma": sma([x.v for x in candles], cfg["volume_ma"]),
    }


def signal_at(symbol, candles, ind, i, cfg):
    """Signal on the CLOSED candle i, or None."""
    if i < warmup(cfg):
        return None
    k = candles[i]
    ef, es, r, a, vm = ind["ema_f"][i], ind["ema_s"][i], ind["rsi"][i], ind["atr"][i], ind["vol_ma"][i]
    if None in (ef, es, r, a, vm):
        return None
    prior_high = max(x.h for x in candles[i - cfg["breakout_lookback"]:i])
    if k.c <= prior_high:
        return None
    if not (ef > es and k.c > es):
        return None
    if not (cfg["rsi_min"] <= r <= cfg["rsi_max"]):
        return None
    if vm and k.v < cfg["volume_mult"] * vm:
        return None
    risk = cfg["atr_stop_mult"] * a
    if risk <= 0 or k.c - risk <= 0:
        return None
    return Signal(symbol, i, k.t, k.c, k.c - risk, k.c + cfg["reward_risk"] * risk, a, r, "breakout")
