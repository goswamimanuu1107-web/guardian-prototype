"""
app.py — thin API layer around scanner.py.

Run locally / in Codespaces with:
    pip install -r requirements.txt
    playwright install chromium
    uvicorn app:app --reload --port 8000

Endpoints:
    POST /api/scan   { "url": "...", "save_as_baseline": true|false }
        -> runs a scan, compares to any saved baseline, returns a report

    GET  /health      -> simple liveness check
"""

from __future__ import annotations

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, HttpUrl

from scanner import run_scan, save_baseline, load_baseline, diff_against_baseline

app = FastAPI(title="Quietbreak — Health Check for AI-Built Apps")

# Wide-open CORS for the prototype stage. Tighten this before real launch.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class ScanRequest(BaseModel):
    url: HttpUrl
    save_as_baseline: bool = False
    confirmed_ownership: bool = False


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/api/scan")
def scan(req: ScanRequest):
    if not req.confirmed_ownership:
        raise HTTPException(
            status_code=400,
            detail="Please confirm you own this app or have permission to test it.",
        )

    url = str(req.url)

    try:
        result = run_scan(url)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Couldn't complete the scan: {e}")

    baseline = load_baseline(url)
    comparison = diff_against_baseline(result, baseline)

    if req.save_as_baseline or baseline is None:
        save_baseline(result)

    ok_count = sum(1 for e in result.elements if e.status == "ok")
    broken_count = sum(1 for e in result.elements if e.status == "broken")

    return {
        "url": url,
        "checked_at": result.timestamp,
        "totals": {
            "ok": ok_count,
            "broken": broken_count,
            "checked": len(result.elements),
        },
        "console_error_count": len(result.console_errors),
        "failed_request_count": len(result.failed_requests),
        "elements": [e.__dict__ for e in result.elements],
        "comparison": comparison,
    }


# Serve the simple frontend directly from this backend for the prototype.
app.mount("/", StaticFiles(directory="../frontend", html=True), name="frontend")
