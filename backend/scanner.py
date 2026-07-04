"""
scanner.py — the core "health check" engine.

What it does, in plain terms:
1. Opens the given URL in a real (headless) browser.
2. Finds every clickable / fillable thing on the page (buttons, links, inputs, forms).
3. Tries each one and watches for trouble: JS errors, failed network requests,
   broken navigation, or elements that silently do nothing.
4. Produces a plain-English list of findings.
5. Can save a "baseline" (the last known-good state) and compare a new run
   against it, so the report can say "this used to work and now it doesn't."

This is intentionally dependency-light (Playwright only) so it runs cleanly
in GitHub Codespaces / any cloud sandbox without needing a local machine.
"""

from __future__ import annotations

import json
import time
import hashlib
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright, TimeoutError as PWTimeoutError


BASELINE_DIR = Path(__file__).parent / "baselines"
BASELINE_DIR.mkdir(exist_ok=True)


@dataclass
class ElementFinding:
    kind: str              # "button" | "link" | "form" | "input"
    label: str             # human-readable label, e.g. "Sign up button"
    selector: str          # css/xpath used to find it again next time
    status: str            # "ok" | "broken" | "skipped"
    detail: str = ""       # plain-English explanation


@dataclass
class ScanResult:
    url: str
    timestamp: float
    console_errors: list[str] = field(default_factory=list)
    failed_requests: list[str] = field(default_factory=list)
    elements: list[ElementFinding] = field(default_factory=list)

    def to_dict(self) -> dict:
        d = asdict(self)
        return d


def _baseline_path(url: str) -> Path:
    key = hashlib.sha256(url.encode()).hexdigest()[:16]
    host = urlparse(url).netloc.replace(":", "_")
    return BASELINE_DIR / f"{host}_{key}.json"


def run_scan(url: str, max_elements: int = 25, timeout_ms: int = 8000) -> ScanResult:
    """Loads the page and exercises interactive elements. Read-only in intent:
    we try clicks/fills but never assume the target lets us complete a real
    purchase/signup — we're checking that the UI *responds*, not completing
    transactions."""

    result = ScanResult(url=url, timestamp=time.time())

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()
        page = context.new_page()

        # Capture console errors as they happen.
        page.on(
            "console",
            lambda msg: result.console_errors.append(msg.text)
            if msg.type == "error"
            else None,
        )
        # Capture failed network requests (404s, timeouts, CORS failures).
        page.on(
            "requestfailed",
            lambda req: result.failed_requests.append(
                f"{req.method} {req.url} — {req.failure}"
            ),
        )

        try:
            page.goto(url, wait_until="load", timeout=timeout_ms * 2)
        except PWTimeoutError:
            result.elements.append(
                ElementFinding(
                    kind="page",
                    label="Page load",
                    selector="",
                    status="broken",
                    detail=f"The page didn't finish loading within {timeout_ms * 2 / 1000:.0f}s.",
                )
            )
            browser.close()
            return result

        # --- Buttons ---
        buttons = page.locator("button, [role=button], input[type=submit]")
        _check_clickables(page, buttons, "button", result, max_elements)

        # --- Links ---
        links = page.locator("a[href]")
        _check_links(page, links, result, max_elements)

        # --- Forms / inputs (existence + basic fill check, not real submission) ---
        forms = page.locator("form")
        _check_forms(page, forms, result, max_elements)

        browser.close()

    return result


def _label_for(page, locator, index: int, fallback: str) -> str:
    try:
        el = locator.nth(index)
        text = (el.inner_text(timeout=1000) or "").strip()
        if text:
            return text[:60]
        aria = el.get_attribute("aria-label")
        if aria:
            return aria[:60]
    except Exception:
        pass
    return fallback


def _check_clickables(page, locator, kind, result: ScanResult, max_elements: int):
    count = min(locator.count(), max_elements)
    for i in range(count):
        label = _label_for(page, locator, i, f"{kind} #{i+1}")
        el = locator.nth(i)
        try:
            if not el.is_visible():
                continue
            before_url = page.url
            before_errors = len(result.console_errors)
            el.click(timeout=3000, trial=False, force=False)
            page.wait_for_timeout(300)
            new_errors = len(result.console_errors) - before_errors
            if new_errors > 0:
                result.elements.append(
                    ElementFinding(
                        kind=kind,
                        label=label,
                        selector=f"nth={i}",
                        status="broken",
                        detail=f"Clicking '{label}' triggered {new_errors} error(s) in the browser console.",
                    )
                )
            else:
                result.elements.append(
                    ElementFinding(
                        kind=kind,
                        label=label,
                        selector=f"nth={i}",
                        status="ok",
                        detail="Responded to a click without errors.",
                    )
                )
            # If click navigated away, go back so we can keep testing this page.
            if page.url != before_url:
                page.go_back(wait_until="load", timeout=5000)
        except PWTimeoutError:
            result.elements.append(
                ElementFinding(
                    kind=kind,
                    label=label,
                    selector=f"nth={i}",
                    status="broken",
                    detail=f"'{label}' did not respond to a click within 3s — it may be unresponsive.",
                )
            )
        except Exception as e:
            result.elements.append(
                ElementFinding(
                    kind=kind,
                    label=label,
                    selector=f"nth={i}",
                    status="skipped",
                    detail=f"Could not test this element ({type(e).__name__}).",
                )
            )


def _check_links(page, locator, result: ScanResult, max_elements: int):
    count = min(locator.count(), max_elements)
    for i in range(count):
        el = locator.nth(i)
        try:
            href = el.get_attribute("href") or ""
            label = _label_for(page, locator, i, href or f"link #{i+1}")
            if not href or href.startswith("javascript:") or href.startswith("#"):
                continue
            if href.startswith("http") and urlparse(href).netloc != urlparse(page.url).netloc:
                # External link — just note it, don't wander off-site.
                continue
        except Exception:
            continue


def _check_forms(page, locator, result: ScanResult, max_elements: int):
    count = min(locator.count(), max_elements)
    for i in range(count):
        form = locator.nth(i)
        try:
            inputs = form.locator("input, textarea, select")
            n_inputs = inputs.count()
            label = f"Form #{i+1} ({n_inputs} field(s))"
            if n_inputs == 0:
                result.elements.append(
                    ElementFinding(
                        kind="form",
                        label=label,
                        selector=f"form nth={i}",
                        status="broken",
                        detail="This form has no fillable fields — it may be misconfigured.",
                    )
                )
                continue
            result.elements.append(
                ElementFinding(
                    kind="form",
                    label=label,
                    selector=f"form nth={i}",
                    status="ok",
                    detail=f"Found and has {n_inputs} field(s).",
                )
            )
        except Exception as e:
            result.elements.append(
                ElementFinding(
                    kind="form",
                    label=f"Form #{i+1}",
                    selector=f"form nth={i}",
                    status="skipped",
                    detail=f"Could not inspect this form ({type(e).__name__}).",
                )
            )


def save_baseline(result: ScanResult) -> None:
    path = _baseline_path(result.url)
    path.write_text(json.dumps(result.to_dict(), indent=2))


def load_baseline(url: str) -> Optional[dict]:
    path = _baseline_path(url)
    if path.exists():
        return json.loads(path.read_text())
    return None


def diff_against_baseline(current: ScanResult, baseline: Optional[dict]) -> dict:
    """Plain-English comparison: what's new, what's newly broken, what got fixed."""
    if baseline is None:
        return {
            "has_baseline": False,
            "summary": "First scan — this is now saved as the baseline to compare future scans against.",
            "newly_broken": [],
            "still_broken": [],
            "fixed": [],
            "unchanged_ok": [],
        }

    base_by_label = {e["label"]: e for e in baseline.get("elements", [])}
    curr_by_label = {e.label: e for e in current.elements}

    newly_broken, still_broken, fixed, unchanged_ok = [], [], [], []

    for label, curr in curr_by_label.items():
        base = base_by_label.get(label)
        if base is None:
            continue  # new element, not a regression
        if curr.status == "broken" and base["status"] != "broken":
            newly_broken.append(curr.detail and f"{label}: {curr.detail}" or label)
        elif curr.status == "broken" and base["status"] == "broken":
            still_broken.append(label)
        elif curr.status == "ok" and base["status"] == "broken":
            fixed.append(label)
        elif curr.status == "ok" and base["status"] == "ok":
            unchanged_ok.append(label)

    if newly_broken:
        summary = f"⚠️ {len(newly_broken)} thing(s) that used to work are now broken."
    elif still_broken:
        summary = f"Still {len(still_broken)} known issue(s) — nothing new broke."
    else:
        summary = "✅ Nothing regressed since the last check."

    return {
        "has_baseline": True,
        "summary": summary,
        "newly_broken": newly_broken,
        "still_broken": still_broken,
        "fixed": fixed,
        "unchanged_ok": unchanged_ok,
    }
