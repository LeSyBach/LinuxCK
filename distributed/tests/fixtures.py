"""Synthetic fixtures used only by the isolated simulation."""
import time

import httpx

from distributed.adapters import SYMBOLS, product

PRICES = {"binance": "95000.50", "okx": "95020.50", "bybit": "94980.50"}


def fixture(exchange, offline, request):
    if offline():
        return httpx.Response(503)
    path = request.url.path
    now = int(time.time() * 1000)
    keys = [product(base, exchange) for base in SYMBOLS]
    key = request.url.params.get("symbol")
    price = PRICES[exchange]
    if exchange == "binance":
        if path.endswith("exchangeInfo"):
            body = {"symbols": [dict(symbol=k, status="TRADING", isSpotTradingAllowed=True) for k in keys]}
        elif path.endswith("price"):
            body = [dict(symbol=k, price=price) for k in keys]
        elif path.endswith("bookTicker"):
            body = [dict(symbol=k, bidPrice="94950", askPrice="95100") for k in keys]
        elif path.endswith("24hr"):
            body = [dict(symbol=k, lastPrice=price, volume="2", quoteVolume="190000",
                         priceChangePercent="1.05", closeTime=now, bidPrice="94950", askPrice="95100") for k in keys]
        elif path.endswith("time"):
            body = {"serverTime": now}
        else:
            ms = 60_000 if request.url.params["interval"] == "1m" else 300_000
            opened = now // ms * ms - ms
            body = [[opened, price, "96000", "94000", price, "1", opened+ms-1, price, 0, "0", "0", "0"]]
    elif exchange == "okx":
        if path.endswith("instruments"):
            data = [dict(instId=k, state="live", quoteCcy="USDT") for k in keys]
        elif path.endswith("tickers"):
            data = [dict(instId=k, last=price, open24h="94000", vol24h="2", volCcy24h="190000",
                         bidPx="94950", askPx="95100", ts=str(now)) for k in keys]
        else:
            ms = 60_000 if request.url.params["bar"] == "1m" else 300_000
            opened = now // ms * ms - ms
            data = [[str(opened), price, "96000", "94000", price, "1", "", price, "1"]]
        body = {"code": "0", "data": data}
    else:
        if path.endswith("instruments-info"):
            data = [dict(symbol=key, status="Trading", quoteCoin="USDT")]
        elif path.endswith("tickers"):
            data = [dict(symbol=key,lastPrice=price, volume24h="2", turnover24h="190000",
                         bid1Price="94950", ask1Price="95100", price24hPcnt="0.0105")]
        else:
            ms = int(request.url.params["interval"]) * 60_000
            opened = now // ms * ms - ms
            data = [[str(opened), price, "96000", "94000", price, "1", price]]
        body = {"retCode": 0, "result": {"category": "spot", "list": data}}
    return httpx.Response(200, json=body)
