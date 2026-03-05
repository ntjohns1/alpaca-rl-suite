"""
Web UI Service
FastAPI backend that serves the React SPA and proxies API requests
to the various alpaca-rl-suite microservices.
"""
import logging
import os
from contextlib import asynccontextmanager

import requests
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

# ─────────────────────────────────────────
# Configuration
# ─────────────────────────────────────────
WEB_UI_PORT             = int(os.getenv("WEB_UI_PORT", "3200"))
KAGGLE_SERVICE_URL      = os.getenv("KAGGLE_SERVICE_URL",  "http://kaggle-orchestrator:8011")
BACKTEST_SERVICE_URL    = os.getenv("BACKTEST_SERVICE_URL", "http://backtest:8001")
RL_TRAIN_SERVICE_URL    = os.getenv("RL_TRAIN_SERVICE_URL", "http://rl-train:8004")
DATASET_SERVICE_URL     = os.getenv("DATASET_SERVICE_URL",  "http://dataset-builder:8003")
DASHBOARD_SERVICE_URL   = os.getenv("DASHBOARD_SERVICE_URL","http://dashboard:8020")
MARKET_SERVICE_URL      = os.getenv("MARKET_SERVICE_URL",   "http://market-ingest:3003")
FEATURE_SERVICE_URL     = os.getenv("FEATURE_SERVICE_URL",  "http://feature-builder:8002")
GRAFANA_URL             = os.getenv("GRAFANA_URL", "http://grafana:3000")

SERVICE_MAP = {
    "kaggle":    KAGGLE_SERVICE_URL,
    "backtest":  BACKTEST_SERVICE_URL,
    "rl":        RL_TRAIN_SERVICE_URL,
    "datasets":  DATASET_SERVICE_URL,
    "dashboard": DASHBOARD_SERVICE_URL,
    "market":    MARKET_SERVICE_URL,
    "features":  FEATURE_SERVICE_URL,
}


@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info(f"Web UI service started on port {WEB_UI_PORT}")
    yield


app = FastAPI(title="Alpaca RL Web UI", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ─────────────────────────────────────────
# API Proxy — forwards /api/{service}/... to the correct backend
# ─────────────────────────────────────────
@app.api_route("/api/{service}", methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
async def proxy_no_path(service: str, request: Request):
    """Reverse-proxy API requests to the appropriate microservice (no path)."""
    target_base = SERVICE_MAP.get(service)
    if not target_base:
        return JSONResponse({"error": f"Unknown service: {service}"}, status_code=404)

    url = f"{target_base}/{service}"
    params = dict(request.query_params)

    try:
        body = await request.body()
        headers = {"Content-Type": request.headers.get("content-type", "application/json")}

        resp = requests.request(
            method=request.method,
            url=url,
            params=params,
            data=body if body else None,
            headers=headers,
            timeout=30,
        )

        try:
            content = resp.json()
        except Exception:
            content = resp.text

        return JSONResponse(content=content, status_code=resp.status_code)

    except requests.exceptions.ConnectionError:
        return JSONResponse({"error": f"Service '{service}' unavailable at {target_base}"}, status_code=502)
    except requests.exceptions.Timeout:
        return JSONResponse({"error": f"Service '{service}' timeout"}, status_code=504)


@app.api_route("/api/{service}/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
async def proxy(service: str, path: str, request: Request):
    """Reverse-proxy API requests to the appropriate microservice."""
    target_base = SERVICE_MAP.get(service)
    if not target_base:
        return JSONResponse({"error": f"Unknown service: {service}"}, status_code=404)

    # Construct URL, handling empty paths correctly
    if path:
        url = f"{target_base}/{service}/{path}"
    else:
        url = f"{target_base}/{service}"
    params = dict(request.query_params)

    try:
        body = await request.body()
        headers = {"Content-Type": request.headers.get("content-type", "application/json")}

        resp = requests.request(
            method=request.method,
            url=url,
            params=params,
            data=body if body else None,
            headers=headers,
            timeout=30,
        )

        try:
            content = resp.json()
        except Exception:
            content = resp.text

        return JSONResponse(content=content, status_code=resp.status_code)

    except requests.exceptions.ConnectionError:
        return JSONResponse({"error": f"Service '{service}' unavailable at {target_base}"}, status_code=502)
    except requests.exceptions.Timeout:
        return JSONResponse({"error": f"Service '{service}' timeout"}, status_code=504)


@app.get("/api/config")
def get_config():
    """Return UI configuration (Grafana URL, etc.)."""
    return {
        "grafanaUrl": os.getenv("GRAFANA_EXTERNAL_URL", "http://localhost:3100"),
    }


@app.get("/api/health")
def health():
    return {"status": "ok", "service": "web-ui"}


# ─────────────────────────────────────────
# Serve React SPA (static files)
# ─────────────────────────────────────────
static_dir = os.path.join(os.path.dirname(__file__), "static")
if os.path.exists(static_dir):
    app.mount("/", StaticFiles(directory=static_dir, html=True), name="spa")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=WEB_UI_PORT)
