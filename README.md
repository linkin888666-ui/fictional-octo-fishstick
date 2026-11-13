# BRUCE 台股 AI 雷達 5.0

Existing production: https://bruce-stock-radar.onrender.com

A Python-standard-library service and mobile-friendly HTML/JavaScript interface. Quotes come from official **daily** TWSE and TPEx reports. Technical scores are explicit rules, not an AI forecast or a probability of profit.

## Supported

- Four-digit listed/OTC company code or full company abbreviation lookup. The bundled official company snapshot includes 1,990 companies as of 2026-11-13; ETF, warrants and emerging stocks are outside this release's scope.
- TPEx Gregorian date requests, volume normalized to shares; TWSE official report fallback for redirect errors.
- Five-month historical window; at least 35 valid observations required. Missing/old history is labelled; no demonstration prices on failure.
- SMA5/SMA20, Wilder RSI5/RSI10, EMA12/EMA26 and DIF-minus-signal MACD histogram, prior-20-session volume ratio and closing-price breakout.
- Trend gate requires price above rising 20MA and 5MA above 20MA. RSI5 >90 signals strength/overheating; consecutive RSI10 >=90 days are displayed. All series are unadjusted for corporate actions.
- Functional filters, result-card expansion/favorites, saved watchlist, custom-stock removal, reduced motion, deep links (`?stock=1815`), loading and retry states.
- No intraday quotes, brokerage branch flow, automatic trading, notifications, or calibrated prediction model.

## Run and verify

Runtime has no pip or npm dependencies. `python server.py` listens on `$PORT` or 8765. Render uses `render.yaml`, production branch `main`, health endpoint `/health`.

```bash
python -m unittest -v
npm ci --ignore-scripts --no-audit --no-fund
npm test
python scripts/with_server.py --server "python server.py" --port 8765 -- python scripts/smoke.py
python scripts/with_server.py --server "python server.py" --port 8765 -- python scripts/smoke.py --live
```

The first checks use fixtures and reference calculations. `--live` queries official exchanges for 2330, 1815, 5475 and 6456 and fails on missing months. DOM tests run in jsdom, so they do not prove mobile layout or actual Safari behavior. Perform a separate rendered browser check after deployment.

Refresh company metadata explicitly with `python scripts/refresh_catalog.py`; only successful downloads replace the snapshot. Company names/markets come from the official URLs recorded in `catalog.json`.

`/health` returns `version` and Render's `RENDER_GIT_COMMIT` revision. The settings page shows frontend/service versions. Only the public HTML and JS files are served; source code, deployment files and Git data return 404. API history is cached for 15 minutes; manual refresh bypasses the cache. Requests for the same stock are deduplicated and upstream requests are bounded.

## Reviewed GitHub integration

The Apache-2.0 server-lifecycle helper from `anthropics/skills` is used by the smoke test and CI; see `tools/webapp-testing/NOTICE.md`. The matching BRUCE acceptance skill is installed separately for agent use. Installing it adds verification procedures, not market data or runtime AI features.
