# FinSight AI — financial intelligence that shows its work

Ask a question in plain English ("How would a Category 4 hurricane in the Gulf affect my energy holdings?",
"Explain why my portfolio risk increased", "Which hurricanes formed in 2010?") and watch an evidence-based analysis
come together: which agents are chosen, what each one reads, how long it takes, and the evidence behind every number.

* **The AI understands, Python calculates.** An LLM (Gemini; rule-based fallback) only reads the question. Every figure
  is computed in Python from stored data, deterministically.
* **Evidence, not predictions.** Results describe what happened in comparable past storms, graded for reliability
  (not enough data / no clear effect / weak signal / indicative). Weak evidence is called weak.
* **Everything labelled.** Live vs demo data, assumptions, sources, versions and what is *not* modelled.

## How it works

```
question ─► Query Understanding ─► agent selection ─► agents (LangGraph, sequential) ─► report
                (Gemini | rules)                       Gather    weather · news · markets · history
                                                       Analyze   exposure · stress test · risk · risk drivers
                                                       Synthesize evidence fusion · hedging
```

| Layer | What | Where |
|---|---|---|
| Storm record | NOAA IBTrACS v04r01, North Atlantic since 1980 → PostgreSQL + one semantic document per storm in Pinecone | `backend/app/historical` |
| Market history | EIA, FRED, Yahoo Finance daily series → PostgreSQL | `backend/app/historical/market` |
| Physical impact | BSEE Gulf of Mexico production shut-ins during storms (2011+) | `backend/app/historical/physical` |
| Event study | market-model abnormal returns around each storm, per asset (pure Python) | `backend/app/analytics` |
| Services | evidence fusion, risk drivers, hedging, historical retrieval | `backend/app/services` |
| API | FastAPI; streaming pipeline events at `POST /api/query/stream` | `backend/app/api` |
| UI | Next.js 15 · React 19 · Tailwind 4 · Motion; pages: Overview, Ask, How it works, Portfolio, History, About | `frontend` |

There is **no fixed weighting** of evidence sources. The numeric estimate comes only from measured event studies applied
to the portfolio's real weights; weather, news and live quotes are shown as context beside it.

## Setup

Requirements: Python 3.10+, Node 20+, a PostgreSQL database (local via `docker compose up -d db`, or a hosted one such as Neon).

```bash
cp .env.example .env              # then fill in the keys you have (see below)

# backend
cd backend
python -m venv venv && source venv/bin/activate      # Windows: venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --port 8000                     # http://localhost:8000/docs

# frontend (second terminal)
cd frontend
npm install
npm run dev                                          # http://localhost:3000
```

### Environment variables (`.env`, never committed)

| Variable | Purpose |
|---|---|
| `DATABASE_URL` | PostgreSQL (source of truth for storms, prices, event studies) |
| `PINECONE_API_KEY`, `PINECONE_INDEX_NAME`, `PINECONE_NAMESPACE` | semantic retrieval; empty = structured-only (reported in the API) |
| `LLM_PROVIDER` (`gemini` \| `anthropic` \| `openai`), `LLM_API_KEY`, `LLM_MODEL` | question understanding; without a key the rule-based parser is used |
| `MARKET_API_KEY` (Finnhub), `NEWS_API_KEY` (NewsAPI) | live quotes and headlines; empty = labelled demo data |
| `FRED_API_KEY`, `EIA_API_KEY` | historical macro / oil & gas prices |
| `DEMO_MODE` | `true` = no external calls at all |
| `CORS_ORIGINS`, `NEXT_PUBLIC_API_URL` | browser origin allowed by the API / API URL used by the UI |

### Load the data (once; every step is safe to re-run)

```bash
cd backend
python scripts/import_ibtracs.py --download         # NOAA storms -> PostgreSQL + Pinecone (or --raw-file <csv> --subset since1980)
python scripts/import_market.py                     # EIA / FRED / Yahoo prices (needs FRED_API_KEY, EIA_API_KEY)
python scripts/import_bsee.py                       # BSEE shut-in reports
python scripts/run_event_study.py                   # storm × asset market responses
python scripts/verify_historical.py                 # smoke-check the live stack
```

Raw downloads are kept (with checksums) under `backend/data/raw` and rebuild the database with `--from-raw`; they are
not committed because the scripts recreate them.

## Tests

```bash
cd backend && python -m pytest -q        # 312 tests: parsing, cleaning, statistics, hedging, streaming, API
cd frontend && npx tsc --noEmit && npx next build
```

## Honest limits

FinSight describes the past; it does not predict the next storm and is **not investment advice**. Storm records start in
1980 and shut-in reports in 2011; only holdings with stored price history are measured; the record holds storm tracks and
intensity, not flooding or damage; abnormal returns are measured against the S&P 500 only; hedge tests exclude costs,
taxes and options. The same limits are shown inside the app (About page and every report).
