"""ASGI application entry point."""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .api.routes import router
from .config import ConfigError, get_settings
from .state import get_state

_LOG_LEVELS = {"CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG", "NOTSET"}


def _log_level() -> str:
    """Resolve LOG_LEVEL tolerantly.

    ``logging`` only accepts upper-case level names, so a perfectly ordinary
    ``LOG_LEVEL=info`` -- which is what every container platform's own config
    conventionally uses, including our own render.yaml -- raised
    ``ValueError: Unknown level: 'info'`` at import time and took the whole
    service down before it served a request. A configuration value should
    never be able to do that: normalise it, and fall back loudly rather than
    crashing if it is unrecognisable.
    """
    raw = os.environ.get("LOG_LEVEL", "INFO").strip().upper()
    if raw in _LOG_LEVELS:
        return raw
    print(
        f"LOG_LEVEL={raw!r} is not a recognised logging level; using INFO. "
        f"Valid values: {', '.join(sorted(_LOG_LEVELS))}.",
        flush=True,
    )
    return "INFO"


logging.basicConfig(
    level=_log_level(),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
log = logging.getLogger("nirantar")

DESCRIPTION = """
**Nirantar** closes the gap between finding a health problem and treating it.

India screens superbly and follows up terribly. Tens of crores of people have
been screened for hypertension, diabetes and three cancers; most abnormal
results never reach a clinician. This service models every un-discharged
abnormal result as a **care debt** -- an obligation the health system owes a
named person, with a clinical deadline -- and runs an agent pipeline that
finds the cheapest path to actually discharging it.

The thing that makes it work is pricing the visit honestly. A follow-up at a
district hospital costs a daily-wage household a day's earnings plus fares;
conventional referral software prices that at zero and then blames the
patient for not attending. Nirantar prices it, predicts attendance, and
routes around the cost -- to the mobile unit that will be in the patient's
own panchayat on Thursday, with the medicine already reserved.

Closure requires evidence: a measurement, a dispensing record, a test result.
Every closure is appended to a hash-chained, Ed25519-signed **Impact Ledger**
that anyone can verify without trusting us.

Licensed Apache-2.0. Built for Code for a Billion 2026.
"""


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    state = get_state()
    log.info(
        "Nirantar ready: %d people, %d care obligations (%d open), binding on %s:%d",
        len(state.world.people),
        len(state.world.debts),
        len(state.world.open_debts()),
        settings.host,
        settings.port,
    )
    if settings.host not in {"127.0.0.1", "::1", "localhost"}:
        log.warning(
            "Listening on %s, which is not loopback. This is correct only "
            "behind a platform proxy or inside a container whose port is not "
            "published beyond localhost.",
            settings.host,
        )
    if settings.demo_mode:
        log.info(
            "DEMO_MODE is on: every record served is fictional and aggregate "
            "reads are anonymous by design. Set DEMO_MODE=false (with an OIDC "
            "provider configured) before this process ever sees a real record."
        )
    if not settings.llm_enabled:
        log.info(
            "No ANTHROPIC_API_KEY set: agents will run on their deterministic "
            "cores. The system is designed to work this way."
        )
    yield


app = FastAPI(
    title="Nirantar — continuity of care",
    description=DESCRIPTION,
    version="1.0.0",
    license_info={"name": "Apache-2.0", "url": "https://www.apache.org/licenses/LICENSE-2.0"},
    lifespan=lifespan,
)

_settings = get_settings()

app.add_middleware(
    CORSMiddleware,
    # Named origins only. No wildcard, because a wildcard plus credentials is
    # how a dashboard becomes readable by any page the user happens to visit.
    allow_origins=_settings.cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["Authorization", "Content-Type"],
)

app.include_router(router)


@app.exception_handler(ConfigError)
async def config_error_handler(_request, exc: ConfigError):
    return JSONResponse(status_code=500, content={"detail": str(exc)})


# --- static frontend -------------------------------------------------------
# When the built dashboard is present, one process serves both. Keeps the
# deployment to a single container and avoids a second public surface.

_DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"
if _DIST.is_dir():
    app.mount("/assets", StaticFiles(directory=_DIST / "assets"), name="assets")

    @app.get("/", include_in_schema=False)
    async def index() -> FileResponse:
        return FileResponse(_DIST / "index.html")

    @app.get("/{path:path}", include_in_schema=False)
    async def spa(path: str) -> FileResponse:
        candidate = _DIST / path
        if candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(_DIST / "index.html")


def main() -> None:
    import uvicorn

    settings = get_settings()
    uvicorn.run(
        "nirantar.main:app",
        host=settings.host,
        port=settings.port,
        # uvicorn wants the lower-case spelling; same validated value.
        log_level=_log_level().lower(),
    )


if __name__ == "__main__":
    main()
