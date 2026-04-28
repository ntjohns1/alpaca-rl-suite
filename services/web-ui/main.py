"""
Web UI Service
FastAPI backend that serves the React SPA and proxies API requests
to the various alpaca-rl-suite microservices.
"""
import logging
import os
from contextlib import asynccontextmanager

import httpx
from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from auth import get_current_user, keycloak_auth

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

# CORS — explicit allowlist; empty by default (same-origin deployment).
# Set CORS_ORIGINS to a comma-separated list for cross-origin dev (e.g. Vite at :5173).
CORS_ORIGINS = [o.strip() for o in os.getenv("CORS_ORIGINS", "").split(",") if o.strip()]

PROXY_TIMEOUT_S = float(os.getenv("PROXY_TIMEOUT_S", "30"))

SERVICE_MAP = {
    "kaggle":    KAGGLE_SERVICE_URL,
    "backtest":  BACKTEST_SERVICE_URL,
    "rl":        RL_TRAIN_SERVICE_URL,
    "datasets":  DATASET_SERVICE_URL,
    "dashboard": DASHBOARD_SERVICE_URL,
    "market":    MARKET_SERVICE_URL,
    "features":  FEATURE_SERVICE_URL,
}

# Headers we never forward upstream (hop-by-hop or set by httpx itself).
_HOP_BY_HOP = {
    "host", "connection", "keep-alive", "proxy-authenticate",
    "proxy-authorization", "te", "trailers", "transfer-encoding", "upgrade",
    "content-length",
}


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.http = httpx.AsyncClient(timeout=PROXY_TIMEOUT_S)
    log.info("Web UI service started on port %d", WEB_UI_PORT)
    log.info("Keycloak issuer: %s", keycloak_auth.issuer)
    try:
        yield
    finally:
        await app.state.http.aclose()


app = FastAPI(title="Alpaca RL Web UI", lifespan=lifespan)

if CORS_ORIGINS:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type"],
    )


# ─────────────────────────────────────────
# Authentication endpoints
# ─────────────────────────────────────────
@app.get("/api/auth/config")
async def get_auth_config():
    """Return Keycloak configuration for frontend bootstrap."""
    return {
        "url": keycloak_auth.server_url,
        "realm": keycloak_auth.realm,
        "clientId": keycloak_auth.client_id,
    }


@app.get("/api/auth/userinfo")
async def get_user_info(user: dict = Depends(get_current_user)):
    """Return current user information."""
    return user


# ─────────────────────────────────────────
# API Proxy — forwards /api/{service}/... to the correct backend
# ─────────────────────────────────────────
@app.api_route(
    "/api/{service}/{path:path}",
    methods=["GET", "POST", "PUT", "DELETE", "PATCH"],
)
async def proxy(
    service: str,
    path: str,
    request: Request,
    user: dict = Depends(get_current_user),
):
    """Reverse-proxy authenticated API requests to the appropriate microservice."""
    if service == "auth":
        return JSONResponse({"error": "Not found"}, status_code=404)

    target_base = SERVICE_MAP.get(service)
    if not target_base:
        return JSONResponse({"error": f"Unknown service: {service}"}, status_code=404)

    # Forward path verbatim under the service namespace (matches the project
    # convention that backend routes are mounted under their own service name).
    upstream_path = f"/{service}" if not path else f"/{service}/{path}"
    url = f"{target_base}{upstream_path}"

    headers = {
        k: v for k, v in request.headers.items()
        if k.lower() not in _HOP_BY_HOP
    }

    try:
        body = await request.body()
        upstream_req = request.app.state.http.build_request(
            method=request.method,
            url=url,
            params=dict(request.query_params),
            content=body if body else None,
            headers=headers,
        )
        upstream_resp = await request.app.state.http.send(upstream_req, stream=True)
    except httpx.ConnectError:
        return JSONResponse(
            {"error": f"Service '{service}' unavailable at {target_base}"},
            status_code=502,
        )
    except httpx.TimeoutException:
        return JSONResponse({"error": f"Service '{service}' timeout"}, status_code=504)
    except Exception:
        log.exception("Proxy error for %s %s", request.method, url)
        return JSONResponse({"error": "Upstream proxy error"}, status_code=500)

    response_headers = {
        k: v for k, v in upstream_resp.headers.items()
        if k.lower() not in _HOP_BY_HOP
    }

    async def stream():
        try:
            async for chunk in upstream_resp.aiter_raw():
                yield chunk
        finally:
            await upstream_resp.aclose()

    return StreamingResponse(
        stream(),
        status_code=upstream_resp.status_code,
        headers=response_headers,
    )


@app.get("/api/config")
async def get_config():
    """Return UI configuration (Grafana URL, etc.)."""
    return {
        "grafanaUrl": os.getenv("GRAFANA_EXTERNAL_URL", "http://localhost:3100"),
    }


@app.get("/api/health")
async def health():
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
