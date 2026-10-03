import os
import json
import asyncio
import threading
import time
from pathlib import Path

from fastapi import FastAPI, Request
from pydantic import BaseModel
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

try:
    from pocketoptionapi.stable_api import PocketOption
except Exception:
    PocketOption = None

BASE = Path(__file__).resolve().parent
app = FastAPI(title="SONIC SIGNAL BOT")
app.mount("/static", StaticFiles(directory=BASE / "static"), name="static")

ASSET = os.getenv("SONIC_ASSET", "EURUSD_otc")
PERIOD = int(os.getenv("SONIC_TIMEFRAME_SECONDS", "60"))
TIMEFRAMES = [5,10,15,30,60,120,180,300,600,900,1800,3600]
ASSETS = []
STATIC_ASSET_FALLBACK = "EURUSD_otc AUDCHF_otc AUDUSD_otc CADCHF_otc CADJPY_otc EURCHF_otc GBPJPY_otc GBPUSD_otc USDCHF_otc USDJPY_otc Gold_otc Silver_otc BrentOil_otc WTICrudeOil_otc Bitcoin_otc Ethereum_otc Solana_otc Tesla_otc Apple_otc Amazon_otc Microsoft_otc SP500_otc US100_otc DJI30_otc".split()
HISTORY = int(os.getenv("SONIC_HISTORY", "300"))
selected_asset = ASSET
selected_period = PERIOD

PO_AUTH_JSON = os.getenv("PO_AUTH_JSON", "").strip()

lock = threading.Lock()
client = None
feed = {
    "feed_connected": False,
    "mode": "NOT_CONFIGURED",
    "asset": ASSET,
    "timeframe": f"{PERIOD}s",
    "period": PERIOD,
    "price": None,
    "timestamp": None,
    "age": None,
    "candles": [],
    "error": None,
    "asset_count": 0,
    "engine": "ADX_DI7_SMOOTH14 + FRACTAL3",
    "signal": "WAIT", "confidence": 0, "reason": "Waiting for qualifying setup",
    "fractal": None, "plus_di": None, "minus_di": None, "plus_strength": 0, "minus_strength": 0, "wide_cross": False,
    "dmi_series": [], "fractal_marks": [],
}

def parse_auth(raw):
    if not raw:
        return ""
    try:
        data = json.loads(raw)
        if isinstance(data, dict):
            for key in ("ssid", "session", "session_id", "user_ssid"):
                value = data.get(key)
                if value:
                    return str(value).strip()
            if isinstance(data.get("auth"), dict):
                for key in ("ssid", "session", "session_id", "user_ssid"):
                    value = data["auth"].get(key)
                    if value:
                        return str(value).strip()
        elif isinstance(data, list):
            # Support Socket.IO-style auth payloads without exposing the secret.
            for item in data:
                if isinstance(item, dict):
                    for key in ("ssid", "session", "session_id", "user_ssid"):
                        value = item.get(key)
                        if value:
                            return str(value).strip()
    except Exception:
        pass
    return raw

def normalize_tick(item):
    if isinstance(item, dict):
        ts = item.get("timestamp", item.get("time", time.time()))
        price = item.get("price", item.get("value", item.get("close")))
        return float(ts), float(price) if price is not None else None
    if isinstance(item, (list, tuple)) and len(item) >= 2:
        return float(item[0]), float(item[1])
    return None, None

def build_candles(ticks, period):
    buckets = {}
    for ts, price in ticks:
        bucket = int(ts // period) * period
        if bucket not in buckets:
            buckets[bucket] = {"time": bucket, "open": price, "high": price, "low": price, "close": price}
        else:
            c = buckets[bucket]
            c["high"] = max(c["high"], price)
            c["low"] = min(c["low"], price)
            c["close"] = price
    return [buckets[k] for k in sorted(buckets)][-HISTORY:]



def _wilder(vals, n):
    if len(vals) < n: return []
    out=[sum(vals[:n])/n]; prev=out[0]
    for v in vals[n:]:
        prev=((prev*(n-1))+v)/n; out.append(prev)
    return out

def _adx(candles, di_length=7, adx_smoothing=14):
    # Sonic uses +DI / -DI for the decision. DI only needs the configured
    # DI length; do not block the panel on the separate ADX smoothing window.
    if len(candles)<di_length+1: return None
    h=[c["high"] for c in candles]; l=[c["low"] for c in candles]; cl=[c["close"] for c in candles]
    tr=[]; plus=[]; minus=[]
    for j in range(1,len(candles)):
        up=h[j]-h[j-1]; down=l[j-1]-l[j]
        plus.append(up if up>down and up>0 else 0); minus.append(down if down>up and down>0 else 0)
        tr.append(max(h[j]-l[j],abs(h[j]-cl[j-1]),abs(l[j]-cl[j-1])))
    atr=_wilder(tr,di_length); ps=_wilder(plus,di_length); ms=_wilder(minus,di_length)
    q=min(len(atr),len(ps),len(ms))
    if q<3:return None
    p=[ps[j]/atr[j]*100 if atr[j] else 0 for j in range(q)]
    mn=[ms[j]/atr[j]*100 if atr[j] else 0 for j in range(q)]
    dx=[(abs(p[j]-mn[j])/max(1e-9,p[j]+mn[j]))*100 for j in range(q)]
    adx_vals=_wilder(dx,adx_smoothing)
    adx=adx_vals[-1] if adx_vals else 0
    return {"plus":p[-1],"minus":mn[-1],"plus_prev":p[-2],"minus_prev":mn[-2],"adx":adx}

def _ema(values, period):
    if len(values) < period: return None
    k = 2.0 / (period + 1.0)
    e = sum(values[:period]) / period
    for v in values[period:]:
        e = (v - e) * k + e
    return e

def _ema_trend(candles):
    closes=[float(x["close"]) for x in candles]
    e9=_ema(closes,9); e20=_ema(closes,20)
    if e9 is None or e20 is None: return None
    return {"ema9":e9,"ema20":e20,"bullish":e9>e20,"bearish":e9<e20}

def _fractal3(c):
    if len(c)<5:return None
    h=[x["high"] for x in c]; l=[x["low"] for x in c]; j=len(c)-3
    if h[j]>h[j-1] and h[j]>h[j-2] and h[j]>h[j+1] and h[j]>h[j+2]: return "DOWN"
    if l[j]<l[j-1] and l[j]<l[j-2] and l[j]<l[j+1] and l[j]<l[j+2]: return "UP"
    return None

def _evaluate(c):
    d=_adx(c,7,14)
    if not d:
        return "WAIT",0,"Waiting for ADX DI 7/14 data",None,d

    trend=_ema_trend(c)
    if not trend:
        return "WAIT",0,"Waiting for EMA 9/20 data",None,d

    # Most recent confirmed Fractal 3.
    f=None
    start=len(c)-3
    stop=max(2,len(c)-11)
    for i in range(start,stop-1,-1):
        h=c[i]["high"]; l=c[i]["low"]
        if h>c[i-1]["high"] and h>c[i-2]["high"] and h>c[i+1]["high"] and h>c[i+2]["high"]:
            f="DOWN"; break
        if l<c[i-1]["low"] and l<c[i-2]["low"] and l<c[i+1]["low"] and l<c[i+2]["low"]:
            f="UP"; break

    gap=abs(d["plus"]-d["minus"])
    # V4 minimum DI separation: avoid firing on nearly tied DI lines.
    if gap < 6.0:
        return "WAIT",0,"DI separation below V4 threshold (6)",f,d

    # Confirm the latest completed candle agrees with the proposed direction.
    last=c[-1]
    bullish_candle=last["close"] > last["open"]
    bearish_candle=last["close"] < last["open"]

    if f == "UP":
        if d["minus"] < d["plus"]:
            return "WAIT",0,"Fractal UP but +DI is dominant",f,d
        if trend["bullish"]:
            return "WAIT",0,"Fractal UP + −DI conflict with EMA 9/20",f,d
        if not bearish_candle:
            return "WAIT",0,"PUT candle confirmation not bearish",f,d
        conf=round(min(99.0,90.0+gap*0.45))
        return "PUT",conf,"V4: Fractal UP + −DI + bearish candle + EMA 9/20",f,d

    if f == "DOWN":
        if d["plus"] < d["minus"]:
            return "WAIT",0,"Fractal DOWN but −DI is dominant",f,d
        if trend["bearish"]:
            return "WAIT",0,"Fractal DOWN + +DI conflict with EMA 9/20",f,d
        if not bullish_candle:
            return "WAIT",0,"CALL candle confirmation not bullish",f,d
        conf=round(min(99.0,90.0+gap*0.45))
        return "CALL",conf,"V4: Fractal DOWN + +DI + bullish candle + EMA 9/20",f,d

    return "WAIT",0,"No confirmed Fractal 3",None,d

