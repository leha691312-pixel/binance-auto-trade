"""Replay the strategy on historical candles with the same fees, slippage and
risk sizing as the bot. Entry = next candle open. Stop wins if both hit."""
from .risk import d
from .strategy import prepare, signal_at, warmup


def backtest(candles, cfg, symbol="SYMBOL"):
    ind = prepare(candles, cfg)
    fee, slip = cfg["fee_pct"] / 100.0, cfg["slippage_pct"] / 100.0
    equity = start = float(cfg["account_equity"])
    max_bars = int(cfg["max_hold_hours"] * 3600000 / max(1, candles[0].ct - candles[0].t + 1)) if candles else 0
    trades, curve = [], [equity]
    i, n = warmup(cfg), len(candles)
    while i < n - 1:
        sig = signal_at(symbol, candles, ind, i, cfg)
        if not sig:
            i += 1
            continue
        e = i + 1
        entry = candles[e].o * (1 + slip)
        risk = sig.entry - sig.stop
        stop, target = entry - risk, entry + cfg["reward_risk"] * risk
        qty = min(cfg["max_loss_per_trade_usd"] / (risk + fee * (entry + stop)),
                  cfg["max_position_pct"] / 100.0 * equity / entry)
        if qty <= 0 or stop <= 0:
            i += 1
            continue
        exit_price, reason, j = None, None, e
        while j < n:
            c = candles[j]
            if c.l <= stop:
                exit_price, reason = min(stop, c.o) * (1 - slip), "stop"
            elif c.h >= target:
                exit_price, reason = target, "target"
            elif j - e >= max_bars:
                exit_price, reason = c.c * (1 - slip), "time"
            if reason:
                break
            j += 1
        if reason is None:                                   # data ended mid-trade
            break
        pnl = qty * (exit_price - entry) - fee * qty * (entry + exit_price)
        r = pnl / (qty * risk)
        equity += pnl
        curve.append(equity)
        trades.append({"entry_t": candles[e].t, "entry": entry, "exit": exit_price,
                       "reason": reason, "pnl": pnl, "r": r})
        i = j + 1
    return summarize(trades, curve, start, candles)


def summarize(trades, curve, start, candles):
    wins = [t for t in trades if t["pnl"] > 0]
    gross_win = sum(t["pnl"] for t in wins)
    gross_loss = -sum(t["pnl"] for t in trades if t["pnl"] <= 0)
    peak, dd = curve[0], 0.0
    for v in curve:
        peak = max(peak, v)
        dd = max(dd, (peak - v) / peak * 100.0)
    return {
        "trades": len(trades),
        "win_rate_pct": 100.0 * len(wins) / len(trades) if trades else 0.0,
        "avg_r": sum(t["r"] for t in trades) / len(trades) if trades else 0.0,
        "profit_factor": gross_win / gross_loss if gross_loss > 0 else (float("inf") if gross_win > 0 else 0.0),
        "total_pnl": curve[-1] - start,
        "return_pct": (curve[-1] / start - 1) * 100.0,
        "max_drawdown_pct": dd,
        "buy_hold_pct": (candles[-1].c / candles[0].c - 1) * 100.0 if candles else 0.0,
        "exits": {k: sum(1 for t in trades if t["reason"] == k) for k in ("target", "stop", "time")},
    }
