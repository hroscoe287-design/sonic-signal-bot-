import os
import json
import threading
import time
from pathlib import Path

from fastapi import FastAPI
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
HISTORY = int(os.getenv("SONIC_HISTORY", "300"))
PO_AUTH_JSON = os.getenv("PO_AUTH_JSON", "").strip()
POCKET_URL = os.getenv("POCKET_URL", "").strip()

lock = threading.Lock()
client = None
feed = {
    "feed_connected": False,
    "mode": "NOT_CONFIGURED",
    "asset": ASSET,
    "timeframe": f"{PERIOD}s",
    "price": None,
    "timestamp": None,
    "age": None,
    "candles": [],
    "error": None,
    "engine": "FRACTAL_3 + DMI_PLUS_MINUS",
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
            # Preserve Ichigo's common Socket.IO auth shape.
            if data.get("auth") and isinstance(data["auth"], dict):
                for key in ("ssid", "session", "session_id", "user_ssid"):
                    value = data["auth"].get(key)
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
        client.subscribe(ASSET, period=PERIOD)
        with lock:
            feed["feed_connected"] = True
            feed["mode"] = "POCKET_OPTION"
            feed["error"] = None
        while True:
            try:
                ticks = client.get_realtime_ticks(ASSET, limit=max(500, HISTORY * PERIOD // 2))
                normalized = []
                for item in ticks or []:
                    ts, price = normalize_tick(item)
                    if ts is not None and price is not None:
                        normalized.append((ts, price))
                if normalized:
                    candles = build_candles(normalized)
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
            time.sleep(0.25)
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
            "engine": "SONIC_FRACTAL_DMI",
        }
