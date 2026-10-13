# ELO Stats

Game-by-game **Elo ratings for every NBA player since 1996-97**, with player profiles, career
stats and an interactive rating history.

- **Backend:** Python, FastAPI, SQLite, [`nba_api`](https://github.com/swar/nba_api)
- **Frontend:** React 19, TypeScript, Vite, TanStack Query, Recharts

---

## How the rating works

Every player starts at **1500**. After each regular-season and playoff game:

1. Each team's strength is the **minutes-weighted average** of its players' pre-game ratings.
2. The home team gets **+100** when computing the expected result.
3. The team swing is `K × MOV multiplier × (result − expected)` with **K = 20**, using
   FiveThirtyEight's margin-of-victory multiplier (bigger wins count more; blowouts by heavy
   favourites are damped).
4. Each player receives that swing scaled by the **share of the game they played**.
5. At the start of each new season, ratings regress **25%** toward 1500.

The engine is a pure function in [`backend/src/elo_stats/elo.py`](backend/src/elo_stats/elo.py).
Its constants live in `EloParams`.

> A rating only moves with wins and losses, so it measures how much a player's minutes go with
> winning against the opponents they faced. It does not measure box-score production.

---

## Getting started

### Prerequisites

- Python 3.11+
- Node.js 22.22+ or 24.15+ (newer jsdom releases used by the tests require it)

### 1. Backend

```bash
cd backend
python -m venv .venv
.venv/Scripts/activate        # Windows (Git Bash: source .venv/Scripts/activate)
# source .venv/bin/activate   # macOS / Linux
pip install -e ".[dev]"
```

Download the game logs and compute ratings. This runs once and caches everything in
`backend/data/elo_stats.sqlite3`:

```bash
python -m elo_stats.ingest
```

- Seasons are fetched **newest first**, so recent data is usable quickly.
- Each season is first requested in one bulk call, which takes seconds when stats.nba.com is
  healthy. If that call times out (it often does), the downloader reads the season schedule and
  fetches **every game's box score** instead, about 1,300 requests per season. Each game is saved
  as it arrives, so an interrupted run resumes where it stopped.
- Requests are paced (`--rate`, default 1.5 per second, `--workers` in parallel). If the site
  starts failing everything, which is how it throttles heavy clients, the downloader pauses for 5
  minutes (doubling up to 30) before continuing.
- Incomplete seasons are retried automatically (`--passes`, default 3). Anything still missing
  is listed at the end, the exit code is `2`, and the app shows a "ratings are provisional" note.
  **Re-run the same command** to fill gaps; completed seasons are never downloaded again.
- Progress is logged to the terminal and to `backend/data/ingest.log`.
- `--skip-fetch` recomputes Elo from cached data, `--refresh` re-downloads everything,
  `--no-bulk` uses box scores only, and `--from-season` / `--to-season` limit the range.

Start the API:

```bash
uvicorn elo_stats.api:create_app --factory --reload
```

### 2. Frontend

From the repository root:

```bash
npm install
npm run dev
```

Open http://localhost:5173. The Vite dev server proxies `/api` to `http://127.0.0.1:8000`; set
`ELO_STATS_API_URL` to point it elsewhere. For a production build served separately from the
API, set `VITE_API_BASE_URL` at build time.

---

## API

All responses use one envelope: `{ "success": bool, "data": ..., "error": str | null, "meta": {...} | null }`.

| Endpoint | Description |
| --- | --- |
| `GET /api/health` | Liveness and whether ratings exist |
| `GET /api/meta` | Seasons covered, last game date, Elo parameters, missing seasons |
| `GET /api/players/search?q=jokic` | Accent-insensitive name search |
| `GET /api/players/{id}` | Current/peak Elo and ranks |
| `GET /api/players/{id}/elo` | Full game-by-game rating history |
| `GET /api/players/{id}/bio` | Bio from stats.nba.com (cached 24h) |
| `GET /api/players/{id}/career` | Per-game averages, eFG%, TS% (cached 24h) |
| `GET /api/leaderboard?sort=current\|peak&active_only=true&min_games=82&limit=25` | Rankings |

Interactive docs: http://127.0.0.1:8000/docs

### Configuration (environment variables)

| Variable | Default |
| --- | --- |
| `ELO_STATS_DB` | `backend/data/elo_stats.sqlite3` |
| `ELO_STATS_CORS_ORIGINS` | `http://localhost:5173,http://127.0.0.1:5173` |
| `ELO_STATS_CACHE_TTL_HOURS` | `24` |
| `ELO_STATS_RATE_LIMIT_PER_MINUTE` | `120` (per client IP, in-memory) |
| `ELO_STATS_NBA_TIMEOUT` | `60` seconds |

---

## Development

```bash
# frontend (repo root)
npm test                # vitest
npm run test:coverage
npm run lint
npm run typecheck
npm run build

# backend (backend/)
pytest --cov=elo_stats
ruff check src tests && ruff format --check src tests
```

## Project structure

```
elo_stats/
├── backend/
│   ├── pyproject.toml
│   ├── src/elo_stats/
│   │   ├── elo.py          # pure Elo engine
│   │   ├── ingest.py       # download + compute CLI
│   │   ├── nba_client.py   # throttled, retrying nba_api wrapper
│   │   ├── repository.py   # SQL queries + response cache
│   │   ├── services.py     # bio / career shaping
│   │   ├── api.py          # FastAPI app factory and routes
│   │   └── ...
│   └── tests/
├── src/
│   ├── api/                # typed client + React Query hooks
│   ├── components/         # Sidebar, PlayerSearch, EloChart, StatsTable, ...
│   ├── pages/              # Leaderboard, Player, About
│   ├── lib/                # formatting and chart-series helpers
│   └── styles/index.css    # light/dark theme tokens
├── index.html
└── vite.config.ts
```

## Known limitations

- The Elo system is heavily influenced by team strength rather than individual performance.
  Ratings move only with wins and losses, and every player on the floor shares their team's
  result, scaled by minutes played. Role players on great teams can therefore outrank stars on
  weak teams, and teammates with similar minutes end up with similar ratings.
- Ratings start in 1996-97. Players whose careers began earlier start that season at 1500.
- PER and Win Shares are not in the public stats.nba.com endpoints used here, so the stats table
  shows eFG% and TS% instead.
- The rate limiter and API cache are in-process, which suits a single server instance.
