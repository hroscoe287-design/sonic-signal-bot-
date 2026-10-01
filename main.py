from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pathlib import Path
import random
import time

BASE = Path(__file__).resolve().parent
app = FastAPI(title="SONIC SIGNAL BOT")
app.mount("/static", StaticFiles(directory=BASE / "static"), name="static")

@app.get("/")
async def home():
    return FileResponse(BASE / "static" / "index.html")

@app.get("/api/state")
async def state():
    # UI/demo feed only. Replace this source with the live candle feed later.
    price = 1.13900 + random.uniform(-0.0012, 0.0012)
    return {
        "feed_connected": False,
        "mode": "DEMO_FEED",
        "asset": "EURUSD_otc",
        "timeframe": "1m",
        "price": round(price, 5),
        "timestamp": time.time(),
        "engine": "FRACTAL_3 + DMI_PLUS_MINUS",
    }

@app.get("/api/health")
async def health():
    return {"ok": True, "engine": "SONIC_FRACTAL_DMI"}

