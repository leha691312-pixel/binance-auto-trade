import json
import os
import time


class Store:
    def __init__(self, path, start_cash):
        self.path = path
        self.data = {"positions": [], "closed": [], "seen": {}, "paper_cash": float(start_cash)}
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                self.data.update(json.load(f))

    def save(self):
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.data, f, indent=2)
        os.replace(tmp, self.path)

    def close(self, trade):
        self.data["positions"] = [p for p in self.data["positions"] if p["id"] != trade["id"]]
        self.data["closed"].append(trade)

    def stats(self, now_ms=None):
        now_ms = now_ms or int(time.time() * 1000)
        day = now_ms - now_ms % 86400000          # UTC midnight
        closed_today = [t for t in self.data["closed"] if t["closed_at"] >= day]
        opened_today = [p for p in self.data["positions"] if p["opened_at"] >= day]
        opened_today += [t for t in self.data["closed"] if t["opened_at"] >= day]
        pnl = sum(t["pnl"] for t in closed_today)
        return {"daily_pnl": pnl, "daily_loss": max(0.0, -pnl), "trades_today": len(opened_today)}
