# Quietbreak — v0 prototype

A plain-English health check for apps built with AI tools (Lovable, Bolt,
Replit, Base44, etc). Paste a URL, Quietbreak clicks through the buttons,
links, and forms like a real user and tells you what works and what's
broken — no code-reading required.

This is a **v0 prototype**, built to prove the core idea works before we
put real design/marketing effort in. It is not production-ready (see
"Known limitations" below).

## How it works

- `backend/scanner.py` — opens the page in a headless browser (Playwright),
  finds interactive elements, tries each one, and watches for JS errors /
  failed network requests / unresponsive elements.
- `backend/app.py` — a small API (FastAPI) that runs a scan and compares it
  to the last saved "baseline" so it can say *"this used to work and now
  doesn't."*
- `frontend/index.html` — a single-page UI: paste a URL, see the report.

## Running it with ZERO load on your own PC

This is built to run entirely in the cloud, exactly as we discussed —
your laptop only needs a browser tab open.

**Recommended: GitHub Codespaces (free tier — 60 hrs/month)**

1. Push this folder to a new GitHub repo (free).
2. On the repo page: **Code → Codespaces → Create codespace on main**.
   This spins up a cloud VM — nothing installs on your PC.
3. Inside the Codespace terminal (still all cloud-side):
   ```bash
   cd backend
   pip install -r requirements.txt
   playwright install chromium --with-deps
   uvicorn app:app --host 0.0.0.0 --port 8000
   ```
4. Codespaces will pop up a forwarded-port link — open it in your browser.
   That's your live prototype, running entirely in the cloud.

**Alternative:** Google Jules can also scaffold/run this in its own cloud
sandbox if you'd rather stay inside one tool for both coding and running.

## Consent check (already built in — from our legal/safety discussion)

The scan endpoint refuses to run unless `confirmed_ownership: true` is
sent — the frontend enforces this with a checkbox: *"I own this app, or I
have permission to test it."* Keep this in every future version. Don't
remove it even if a future feature wants to make scanning "one click
faster" — it's the thing standing between us and testing someone else's
site without permission.

## Known limitations (fine for v0, fix before real launch)

- Link-checking (`_check_links` in `scanner.py`) currently only skips
  external links — it doesn't yet verify internal links resolve. Next
  iteration should follow same-site links and flag 404s.
- No user accounts / auth yet — baselines are stored as local files keyed
  by URL. Fine for one person testing one app; needs a real database
  before multiple users share this.
- No rate-limiting — someone could point this at a huge site and it'd try
  to click 25+ elements per category. Fine for a prototype demo.
- "Broken" detection is based on console errors / unresponsiveness, not
  business logic — it can't yet tell you *"checkout charged the wrong
  amount,"* only *"checkout button threw an error."* That's a v2 problem.

## What's next (per our plan)

1. ✅ Working prototype (this)
2. → Landing page + waitlist (to validate real demand before polishing further)
3. → Product name, branding, and the exact v1 feature list
