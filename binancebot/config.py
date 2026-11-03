import json
import os

DEFAULTS = {
    # "paper" = simulate locally on real market data, no orders sent
    # "testnet" = real orders on Binance Spot Testnet (fake money)
    # "live"  = real money. Needs BINANCE_LIVE_CONFIRM=I_ACCEPT_THE_RISK
    "mode": "paper",
    "base_url": "",
    "symbols": ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT"],
    "quote_asset": "USDT",
    "interval": "15m",
    "poll_seconds": 60,
    "account_equity": 1000.0,          # paper starting cash
    # strategy
    "ema_fast": 20, "ema_slow": 50, "rsi_period": 14, "rsi_min": 50, "rsi_max": 72,
    "atr_period": 14, "atr_stop_mult": 1.5, "reward_risk": 2.0,
    "breakout_lookback": 20, "volume_ma": 20, "volume_mult": 1.2,
    "max_hold_hours": 24,
    # risk
    "max_loss_per_trade_usd": 10.0,
    "daily_loss_limit_usd": 30.0,
    "max_trades_per_day": 5,
    "max_open_positions": 2,
    "max_position_pct": 25.0,
    "min_reward_risk": 1.5,
    "min_stop_pct": 0.2, "max_stop_pct": 8.0,
    "fee_pct": 0.1, "slippage_pct": 0.05,
    "require_confirm": True,           # live only: ask y/N before every order
    "state_file": "state.json",
    "kill_file": "KILL",
}


def load(path=None):
    cfg = dict(DEFAULTS)
    path = path or ("config.json" if os.path.exists("config.json") else None)
    if path:
        with open(path, encoding="utf-8") as f:
            user = json.load(f)
        unknown = set(user) - set(DEFAULTS)
        if unknown:
            raise ValueError("unknown config keys: %s" % ", ".join(sorted(unknown)))
        cfg.update(user)
    if cfg["mode"] not in ("paper", "testnet", "live"):
        raise ValueError("mode must be paper, testnet or live")
    return cfg
