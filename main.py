import os
import json
import asyncio
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
    if len(candles)<di_length+adx_smoothing+2: return None
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

    # Use the most recent confirmed Fractal 3 so Sonic stays fast on 15s
    # charts instead of waiting for a brand-new fractal on every candle.
    f=None
    start=len(c)-3
    stop=max(2,len(c)-11)
    for i in range(start,stop-1,-1):
        h=c[i]["high"]; l=c[i]["low"]
        if h>c[i-1]["high"] and h>c[i-2]["high"] and h>c[i+1]["high"] and h>c[i+2]["high"]:
            f="DOWN"; break
        if l<c[i-1]["low"] and l<c[i-2]["low"] and l<c[i+1]["low"] and l<c[i+2]["low"]:
            f="UP"; break
    # Fast ADX fallback: if a confirmed Fractal 3 is not available yet,
    # do not let Sonic remain stuck on WAIT. The DI relationship itself can
    # trigger a fast signal; a matching Fractal, when present, remains the
    # preferred confirmation path.
    if not f:
        gap=abs(d["plus"]-d["minus"])
        wide=gap>=max(5.0,d["plus"]*.22,d["minus"]*.22)
        if wide:
            conf=round(min(99.0,94.0+gap*0.45))
        elif gap>=3:
            conf=90
        else:
            conf=80
        if d["minus"]>=d["plus"]:
            return "PUT",conf,"ADX DI overlap/dominance (−DI on top)",None,d
        return "CALL",conf,"ADX DI overlap/dominance (+DI on top)",None,d

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
    # Matching Fractal + DI setups remain actionable at the default 80% threshold.
    if wide:
        conf=round(min(99.0, 94.0 + gap*0.45))
    elif gap>=3:
        conf=90
    else:
        conf=80

    if f=="UP" and d["minus"]>=d["plus"]:
        label="WIDE" if wide else ("MEDIUM" if gap>=3 else "SMALL")
        return "PUT",conf,f"Fractal UP + −DI on top ({label})",f,d

    if f=="DOWN" and d["plus"]>=d["minus"]:
        label="WIDE" if wide else ("MEDIUM" if gap>=3 else "SMALL")
        return "CALL",conf,f"Fractal DOWN + +DI on top ({label})",f,d

    return "WAIT",0,"Fractal and DI direction are conflicting",f,d

def _indicator_series(candles, di_length=7, adx_smoothing=14):
    rows=[]
    if len(candles)<di_length+adx_smoothing+2: return rows
    for i in range(4, len(candles)+1):
        d=_adx(candles[:i], di_length, adx_smoothing)
        if d:
            rows.append({"time":candles[i-1]["time"],"plus":round(d["plus"],2),"minus":round(d["minus"],2),"adx":round(d.get("adx",0),2)})
    return rows

def _fractal_marks(candles):
    marks=[]
    if len(candles)<5: return marks
    for i in range(2,len(candles)-2):
        h=candles[i]["high"]; l=candles[i]["low"]
        if h>candles[i-1]["high"] and h>candles[i-2]["high"] and h>candles[i+1]["high"] and h>candles[i+2]["high"]:
            marks.append({"time":candles[i]["time"],"type":"DOWN","price":h})
        elif l<candles[i-1]["low"] and l<candles[i-2]["low"] and l<candles[i+1]["low"] and l<candles[i+2]["low"]:
            marks.append({"time":candles[i]["time"],"type":"UP","price":l})
    return marks

def _subscribe_stream(asset, period):
    """Subscribe using the WebSocket's owning asyncio loop."""
    if not client or not client.check_connect():
        return False, "Pocket Option socket is not connected"
    io_loop = getattr(client, "_io_loop", None)
    ws_client = getattr(getattr(client, "api", None), "websocket", None)
    ws = getattr(ws_client, "websocket", None)
    if io_loop is None or not io_loop.is_running() or ws is None:
        return False, "Pocket Option WebSocket loop is not ready"
    async def send_commands():
        await ws.send('42' + json.dumps(["changeSymbol", {"asset": asset, "period": period}]))
        await ws.send('42' + json.dumps(["subfor", asset]))
    try:
        future = asyncio.run_coroutine_threadsafe(send_commands(), io_loop)
        future.result(timeout=5)
        client.api.current_asset = asset
        client.api.current_period = period
        return True, None
    except Exception as exc:
        return False, str(exc)


def _load_history(asset, period):
    """Load a full candle seed so chart + ADX/DI are populated immediately."""
    if not client:
        return []
    rows=[]
    try:
        rows=client.get_historical_candles(asset, period, offset=max(12000, period*HISTORY*3), count_request=1) or []
    except Exception:
        rows=[]
    normalized=[]
    for item in rows:
        try:
            if isinstance(item, dict):
                ts=float(item.get("time", item.get("timestamp", item.get("ts"))))
                o=float(item["open"]); h=float(item["high"]); l=float(item["low"]); cl=float(item["close"])
            elif isinstance(item,(list,tuple)) and len(item)>=5:
                ts=float(item[0]); o=float(item[1]); cl=float(item[2]); h=float(item[3]); l=float(item[4])
            else:
                continue
            normalized.append({"time":ts,"open":o,"high":h,"low":l,"close":cl})
        except (TypeError,ValueError,KeyError):
            continue
    normalized.sort(key=lambda x:x["time"])
    return normalized[-HISTORY:]


def _seed_dashboard(asset, period):
    candles=_load_history(asset, period)
    if not candles:
        try:
            ticks=client.get_realtime_ticks(asset, limit=max(250, min(1500, HISTORY*max(2,period//2)))) or []
            normalized=[]
            for item in ticks:
                ts,price=normalize_tick(item)
                if ts is not None and price is not None: normalized.append((ts,price))
            candles=build_candles(sorted(normalized),period)
        except Exception:
            candles=[]
    if candles:
        with lock:
            feed["candles"]=candles
            feed["dmi_series"]=_indicator_series(candles,7,14)[-120:]
            feed["fractal_marks"]=_fractal_marks(candles)[-80:]
            feed["price"]=round(float(candles[-1]["close"]),8)
            feed["timestamp"]=float(candles[-1]["time"])
            feed["age"]=max(0.0,time.time()-float(candles[-1]["time"]))
        _update_engine(candles)
    return len(candles)


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
    global client, selected_asset, selected_period
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
            feed["asset"] = selected_asset
            feed["period"] = selected_period
            feed["timeframe"] = f"{selected_period}s"
        if selected_asset not in ASSETS and ASSETS:
            selected_asset = ASSETS[0]
        subscribed, sub_error = _subscribe_stream(selected_asset, selected_period)
        if not subscribed:
            with lock:
                feed["feed_connected"] = False
                feed["error"] = f"Stream subscription failed: {sub_error}"
            return

        # Seed the chart and ADX/DI immediately with historical candles.
        if _seed_dashboard(selected_asset, selected_period) == 0:
            with lock: feed["error"] = "No historical candle data returned"

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
                    limit=max(250, min(1000, HISTORY * max(1, selected_period // 2)))
                )
                normalized = []
                for item in ticks or []:
                    ts, price = normalize_tick(item)
                    if ts is not None and price is not None:
                        normalized.append((ts, price))

                if normalized:
                    normalized.sort(key=lambda x: x[0])
                    candles = build_candles(normalized, selected_period)
                    _update_engine(candles)
                    last_ts, last_price = normalized[-1]
                    with lock:
                        feed["feed_connected"] = True
                        feed["price"] = round(last_price, 5)
                        feed["timestamp"] = last_ts
                        feed["age"] = max(0.0, time.time() - last_ts)
                        feed["candles"] = candles
                        feed["dmi_series"] = _indicator_series(candles, 7, 14)[-120:]
                        feed["fractal_marks"] = _fractal_marks(candles)[-40:]
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

def _asset_category(symbol):
    s = str(symbol).upper().replace("/", "").replace("-", "").replace("_OTC", "")
    # Pocket Option names vary by feed; classify common symbols while
    # keeping the live catalog intact.
    crypto_keys = ("BTC", "ETH", "SOL", "XRP", "DOGE", "LTC", "ADA", "BNB", "TRX", "DOT", "AVAX", "MATIC", "USDT")
    index_keys = ("SP500", "SPX", "US500", "US100", "NAS100", "NASDAQ", "DJI", "DJ30", "DOW", "GER40", "DAX", "UK100", "FTSE", "FRA40", "CAC", "JP225", "NIKKEI", "HK50", "HSI", "AUS200", "ASX")
    commodity_keys = ("GOLD", "XAU", "SILVER", "XAG", "BRENT", "WTI", "CRUDE", "OIL", "NATURALGAS", "COPPER")
    stock_keys = ("APPLE", "TESLA", "AMAZON", "MICROSOFT", "GOOGLE", "ALPHABET", "META", "NVIDIA", "NVDA", "AMD", "NETFLIX", "INTEL", "COINBASE")
    if any(k in s for k in crypto_keys):
        return "Crypto"
    if any(k in s for k in index_keys):
        return "Indices"
    if any(k in s for k in commodity_keys):
        return "Commodities"
    if any(k in s for k in stock_keys):
        return "Stocks"
    # Standard FX symbols are six letters (e.g. EURUSD, AUDCAD).
    if len(s) == 6 and s.isalpha():
        return "Forex"
    if s.endswith("OTC") and len(s) >= 6:
        return "Other"
    return "Other"

@app.get("/api/assets")
async def assets():
    groups = {"Forex": [], "Crypto": [], "Indices": [], "Commodities": [], "Stocks": [], "Other": []}
    for symbol in sorted(set(ASSETS), key=str.upper):
        groups[_asset_category(symbol)].append(symbol)
    return {
        "assets": list(ASSETS),
        "asset_groups": groups,
        "timeframes": TIMEFRAMES,
        "live_catalog": bool(ASSETS),
        "count": len(ASSETS)
    }

class Config(BaseModel):
    asset: str
    timeframe: int

@app.post("/api/config")
async def config(body: Config):
    global selected_asset, selected_period
    if body.asset not in ASSETS or body.timeframe not in TIMEFRAMES:
        return {"ok": False, "error": "Unsupported asset or timeframe"}
    with lock:
        selected_asset, selected_period = body.asset, body.timeframe
        feed["asset"], feed["timeframe"], feed["period"] = body.asset, f"{body.timeframe}s", body.timeframe
        feed["signal"], feed["confidence"] = "WAIT", 0
        feed["reason"] = "Switching live market feed..."
        feed["candles"], feed["dmi_series"], feed["fractal_marks"] = [], [], []
    try:
        if client:
            ok, err = _subscribe_stream(selected_asset, selected_period)
            if not ok:
                with lock:
                    feed["error"] = f"Subscription switch: {err}"
            else:
                # Re-seed after every Apply so the chart and ADX/DI never wait
                # for new candles to rebuild their history.
                if _seed_dashboard(selected_asset, selected_period) == 0:
                    with lock: feed["error"] = "No historical candle data returned"
    except Exception as exc:
        with lock:
            feed["error"] = f"Subscription switch: {exc}"
    return {"ok": True}

@app.get("/api/health")
async def health():
    with lock:
        return {
            "ok": True,
            "feed_connected": feed["feed_connected"],
            "mode": feed["mode"],
            "asset": feed["asset"],
            "timeframe": feed["timeframe"],
            "error": feed["error"],
            "engine": "SONIC_ADX_DI7_SMOOTH14_FRACTAL3",
            "asset_count": feed["asset_count"],
        }
