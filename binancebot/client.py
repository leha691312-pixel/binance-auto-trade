"""Minimal Binance Spot REST client (standard library only)."""
import hashlib
import hmac
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import namedtuple

URLS = {
    "paper": "https://api.binance.com",       # public market data only
    "testnet": "https://testnet.binance.vision",
    "live": "https://api.binance.com",
}

Candle = namedtuple("Candle", "t o h l c v ct")  # open time, OHLCV, close time (ms)


class BinanceError(Exception):
    def __init__(self, msg, status=None):
        super().__init__(msg)
        self.status = status


def sign(secret, query):
    return hmac.new(secret.encode(), query.encode(), hashlib.sha256).hexdigest()


def to_candles(raw):
    return [Candle(int(r[0]), float(r[1]), float(r[2]), float(r[3]), float(r[4]), float(r[5]), int(r[6]))
            for r in raw]


class Client:
    def __init__(self, base_url, api_key="", api_secret="", timeout=15, recv_window=5000):
        self.base = base_url.rstrip("/")
        self.key, self.secret = api_key, api_secret
        self.timeout, self.recv = timeout, recv_window

    def _request(self, method, path, params=None, signed=False):
        params = {k: v for k, v in (params or {}).items() if v is not None}
        headers = {"User-Agent": "binance-auto-trade/1.0"}
        if signed:
            if not self.key or not self.secret:
                raise BinanceError("BINANCE_API_KEY / BINANCE_API_SECRET are not set")
            params["recvWindow"] = self.recv
            params["timestamp"] = int(time.time() * 1000)
            query = urllib.parse.urlencode(params)
            query += "&signature=" + sign(self.secret, query)
            headers["X-MBX-APIKEY"] = self.key
        else:
            query = urllib.parse.urlencode(params)
        url, data = self.base + path, None
        if method == "POST":
            data = query.encode()
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        elif query:
            url += "?" + query
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                return json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            body = e.read().decode(errors="replace")
            raise BinanceError("HTTP %s %s: %s" % (e.code, path, body), e.code)
        except urllib.error.URLError as e:
            raise BinanceError("network error %s: %s" % (path, e.reason))

    # ---- market data (public)
    def klines(self, symbol, interval, limit=500, start=None, end=None):
        raw = self._request("GET", "/api/v3/klines", {
            "symbol": symbol, "interval": interval, "limit": limit,
            "startTime": start, "endTime": end})
        return to_candles(raw)

    def klines_paged(self, symbol, interval, total):
        out, end = [], None
        while len(out) < total:
            want = min(1000, total - len(out))
            batch = self.klines(symbol, interval, want, end=end)
            if not batch:
                break
            out = batch + out
            end = batch[0].t - 1
            if len(batch) < want:
                break
            time.sleep(0.2)
        return out[-total:]

    def exchange_info(self, symbol):
        info = self._request("GET", "/api/v3/exchangeInfo", {"symbol": symbol})
        return info["symbols"][0]

    # ---- account / trading (signed)
    def balances(self):
        acc = self._request("GET", "/api/v3/account", signed=True)
        return {b["asset"]: float(b["free"]) for b in acc["balances"]}

    def market_buy(self, symbol, qty):
        return self._request("POST", "/api/v3/order", {
            "symbol": symbol, "side": "BUY", "type": "MARKET", "quantity": qty,
            "newOrderRespType": "FULL"}, signed=True)

    def market_sell(self, symbol, qty):
        return self._request("POST", "/api/v3/order", {
            "symbol": symbol, "side": "SELL", "type": "MARKET", "quantity": qty,
            "newOrderRespType": "FULL"}, signed=True)

    def oco_sell(self, symbol, qty, take_profit, stop, stop_limit):
        return self._request("POST", "/api/v3/orderList/oco", {
            "symbol": symbol, "side": "SELL", "quantity": qty,
            "aboveType": "LIMIT_MAKER", "abovePrice": take_profit,
            "belowType": "STOP_LOSS_LIMIT", "belowStopPrice": stop,
            "belowPrice": stop_limit, "belowTimeInForce": "GTC",
            "newOrderRespType": "FULL"}, signed=True)

    def order_list(self, list_id):
        return self._request("GET", "/api/v3/orderList", {"orderListId": list_id}, signed=True)

    def cancel_order_list(self, symbol, list_id):
        return self._request("DELETE", "/api/v3/orderList",
                             {"symbol": symbol, "orderListId": list_id}, signed=True)

    def order(self, symbol, order_id):
        return self._request("GET", "/api/v3/order", {"symbol": symbol, "orderId": order_id}, signed=True)
