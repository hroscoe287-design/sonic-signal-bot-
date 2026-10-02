import os
import json
import threading
import time
from pathlib import Path

from fastapi import FastAPI
from pydantic import BaseModel
from fastapi.responses import FileResponse
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
    "engine": "FRACTAL_3 + DMI_PLUS_MINUS",
    "signal": "WAIT", "confidence": 0, "reason": "Waiting for qualifying setup",
    "fractal": None, "plus_di": None, "minus_di": None, "plus_strength": 0, "minus_strength": 0, "wide_cross": False,
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

def build_candles(ticks):
    buckets = {}
    for ts, price in ticks:
        bucket = int(ts // PERIOD) * PERIOD
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

def _dmi(candles, n=7):
    if len(candles)<n+3: return None
    h=[c["high"] for c in candles]; l=[c["low"] for c in candles]; cl=[c["close"] for c in candles]
    tr=[]; plus=[]; minus=[]
    for j in range(1,len(candles)):
        up=h[j]-h[j-1]; down=l[j-1]-l[j]
        plus.append(up if up>down and up>0 else 0); minus.append(down if down>up and down>0 else 0)
        tr.append(max(h[j]-l[j],abs(h[j]-cl[j-1]),abs(l[j]-cl[j-1])))
    atr=_wilder(tr,n); ps=_wilder(plus,n); ms=_wilder(minus,n)
    q=min(len(atr),len(ps),len(ms))
    if q<3:return None
    p=[ps[j]/atr[j]*100 if atr[j] else 0 for j in range(q)]
    mn=[ms[j]/atr[j]*100 if atr[j] else 0 for j in range(q)]
    return {"plus":p[-1],"minus":mn[-1],"plus_prev":p[-2],"minus_prev":mn[-2]}

def _fractal3(c):
    if len(c)<5:return None
    h=[x["high"] for x in c]; l=[x["low"] for x in c]; j=len(c)-3
    if h[j]>h[j-1] and h[j]>h[j-2] and h[j]>h[j+1] and h[j]>h[j+2]: return "DOWN"
    if l[j]<l[j-1] and l[j]<l[j-2] and l[j]<l[j+1] and l[j]<l[j+2]: return "UP"
    return None

def _evaluate(c):
    f=_fractal3(c); d=_dmi(c)
    if not f or not d:
        return "WAIT",0,"Waiting for complete Fractal 3 + DMI setup",f,d

    # Sonic overlap rule:
    # - The Fractal arrow supplies the setup direction.
    # - The DI line on top supplies the directional confirmation.
    # - Do NOT require the winning DI to be rising; this lets small overlaps
    #   produce signals instead of being forced into WAIT.
    # - Confidence scales with DI separation: tight/small overlap = lower
    #   confidence, wide separation = higher confidence.
    gap=abs(d["plus"]-d["minus"])
    baseline=max(1.0,min(100.0,(abs(d["plus"])+abs(d["minus"]))/2.0))
    overlap_ratio=gap/max(1.0,baseline)
    wide=gap>=max(5.0,d["plus"]*.22,d["minus"]*.22)

    # Map the DI relationship into a confidence band. Small gaps stay valid
    # signals, while larger gaps receive materially more confidence.
    conf=round(52.0 + min(46.0, gap*1.9 + overlap_ratio*18.0))
    conf=min(98,max(52,conf))

    if f=="UP" and d["minus"]>=d["plus"]:
        label="WIDE" if wide else ("MEDIUM" if gap>=3 else "SMALL")
        return "PUT",conf,f"Fractal UP + −DI on top ({label} overlap)",f,d

    if f=="DOWN" and d["plus"]>=d["minus"]:
        label="WIDE" if wide else ("MEDIUM" if gap>=3 else "SMALL")
        return "CALL",conf,f"Fractal DOWN + +DI on top ({label} overlap)",f,d

    return "WAIT",0,"Fractal and DI direction are conflicting",f,d

def _update_engine(candles):
    s,conf,reason,f,d=_evaluate(candles)
    with lock:
        feed["signal"],feed["confidence"],feed["reason"]=s,conf,reason
        feed["fractal"]=f
        if d:
            feed["plus_di"],feed["minus_di"]=round(d["plus"],2),round(d["minus"],2)
            feed["plus_strength"]=min(5,max(0,round(d["plus"]/10)))
            feed["minus_strength"]=min(5,max(0,round(d["minus"]/10)))
            feed["wide_cross"]=abs(d["plus"]-d["minus"])>=max(5,d["plus"]*.22,d["minus"]*.22)

def feed_worker():
    global client
    auth = parse_auth(PO_AUTH_JSON)
    if not auth:
        with lock:
            feed["error"] = "PO_AUTH_JSON is not configured"
        return
    if PocketOption is None:
        with lock:
            feed["error"] = "PocketOption client failed to install"
        return

    try:
        client = PocketOption(auth)
        ok, err = client.connect()
        if not ok:
            with lock:
                feed["error"] = str(err or "Pocket Option connection failed")
            return

        live = client.get_assets() or {}
        live_names = [str(symbol) for symbol, info in live.items() if isinstance(info, dict) and info.get("is_available", True)]
        with lock:
            ASSETS.clear()
            ASSETS.extend(sorted(set(live_names or STATIC_ASSET_FALLBACK)))
            feed["asset_count"] = len(ASSETS)
        if selected_asset not in ASSETS and ASSETS:
            selected_asset = ASSETS[0]
        client.subscribe(selected_asset, period=selected_period)
        with lock:
            feed["feed_connected"] = True
            feed["mode"] = "POCKET_OPTION"
            feed["error"] = None

        # Fast polling keeps the dashboard responsive without changing the
        # selected candle timeframe.
        while True:
            cycle_start = time.monotonic()
            try:
                ticks = client.get_realtime_ticks(
                    selected_asset,
                    limit=max(250, min(1000, HISTORY * max(1, PERIOD // 2)))
                )
                normalized = []
                for item in ticks or []:
                    ts, price = normalize_tick(item)
                    if ts is not None and price is not None:
                        normalized.append((ts, price))

                if normalized:
                    normalized.sort(key=lambda x: x[0])
                    candles = build_candles(normalized)
                    _update_engine(candles)
                    last_ts, last_price = normalized[-1]
                    with lock:
                        feed["feed_connected"] = True
                        feed["price"] = round(last_price, 5)
                        feed["timestamp"] = last_ts
                        feed["age"] = max(0.0, time.time() - last_ts)
                        feed["candles"] = candles
                        feed["error"] = None
            except Exception as exc:
                with lock:
                    feed["error"] = str(exc)

            # Target ~100 ms refresh when the client call is fast; never spin
            # at 100% CPU if the provider is slower.
            elapsed = time.monotonic() - cycle_start
            time.sleep(max(0.05, 0.10 - elapsed))

    except Exception as exc:
        with lock:
            feed["feed_connected"] = False
            feed["error"] = str(exc)

@app.on_event("startup")
def start_feed():
    threading.Thread(target=feed_worker, daemon=True, name="pocket-option-feed").start()

@app.get("/")
async def home():
    return FileResponse(BASE / "static" / "index.html")

@app.get("/api/state")
async def state():
    with lock:
        snapshot = dict(feed)
        snapshot["candles"] = list(feed["candles"])
    return snapshot

@app.get("/api/assets")\nasync def assets():\n    return {"assets": list(ASSETS), "timeframes": TIMEFRAMES, "live_catalog": bool(ASSETS), "count": len(ASSETS)}\n\nclass Config(BaseModel):\n    asset: str\n    timeframe: int\n\n@app.post("/api/config")\nasync def config(body: Config):\n    global selected_asset, selected_period\n    if body.asset not in ASSETS or body.timeframe not in TIMEFRAMES:\n        return {"ok": False, "error": "Unsupported asset or timeframe"}\n    with lock:\n        selected_asset, selected_period = body.asset, body.timeframe\n        feed["asset"], feed["timeframe"] = body.asset, f"{body.timeframe}s"\n        feed["signal"], feed["confidence"] = "WAIT", 0\n        feed["reason"] = "Switching live market feed..."\n    return {"ok": True}\n\n@app.get("/api/health")
async def health():
    with lock:
        return {
            "ok": True,
            "feed_connected": feed["feed_connected"],
            "mode": feed["mode"],
            "asset": feed["asset"],
            "timeframe": feed["timeframe"],
            "error": feed["error"],
            "engine": "SONIC_FRACTAL_DMI",
            "asset_count": feed["asset_count"],
        }
