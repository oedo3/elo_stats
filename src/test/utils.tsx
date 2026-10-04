import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render } from '@testing-library/react'
import type { ReactElement } from 'react'
import { MemoryRouter } from 'react-router'
import { vi } from 'vitest'
import type {
  EloPoint,
  LeaderboardEntry,
  Meta,
  PlayerBio,
  PlayerCareer,
  PlayerRating,
  PlayerSearchResult,
  StatLine,
} from '../api/types'

export function renderWithProviders(ui: ReactElement, { route = '/' } = {}) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[route]}>{ui}</MemoryRouter>
    </QueryClientProvider>,
  )
}

type Handler = (url: URL) => { status?: number; body: unknown } | undefined

/** Stubs global fetch. Each handler can claim a URL; unclaimed URLs return 404 envelopes. */
export function mockFetch(handler: Handler) {
  const fn = vi.fn(async (input: RequestInfo | URL) => {
    const url = new URL(String(input), 'http://localhost')
    const result = handler(url) ?? {
      status: 404,
      body: { success: false, data: null, error: 'Not found', meta: null },
    }
    return new Response(JSON.stringify(result.body), {
      status: result.status ?? 200,
      headers: { 'Content-Type': 'application/json' },
    })
  })
  vi.stubGlobal('fetch', fn)
  return fn
}

export const envelope = <T,>(data: T) => ({ success: true, data, error: null, meta: null })

export const META: Meta = {
  has_data: true,
  first_season: 1996,
  last_season: 2025,
  last_game_date: '2026-06-15',
  computed_at: '2026-10-04T18:00:00+00:00',
  elo_params: { initial_rating: 1500, k_factor: 20, home_advantage: 100, season_reversion: 0.25 },
  missing_seasons: [],
}

export const PLAYER: PlayerRating = {
  player_id: 203999,
  player_name: 'Nikola Jokić',
  rating: 1712.4,
  peak_rating: 1755.2,
  peak_date: '2024-03-01',
  games: 900,
  first_game_date: '2015-10-28',
  last_game_date: '2026-06-01',
  last_season: 2025,
  team_abbr: 'DEN',
  is_active: true,
  active_rank: 1,
  peak_rank: 3,
}

export const BIO: PlayerBio = {
  player_id: 203999,
  name: 'Nikola Jokić',
  position: 'Center',
  height: '6-11',
  weight: 284,
  jersey: '15',
  birthdate: '1995-02-19',
  country: 'Serbia',
  school: null,
  team_name: 'Denver Nuggets',
  team_abbr: 'DEN',
  draft_year: 2014,
  draft_round: 2,
  draft_number: 41,
  from_year: 2015,
  to_year: 2026,
  seasons: 11,
  is_active: true,
  greatest_75: false,
}

export const HISTORY: EloPoint[] = [
  {
    game_id: '1',
    game_date: '2023-10-24',
    season: 2023,
    team_abbr: 'DEN',
    opponent_abbr: 'LAL',
    won: true,
    rating_before: 1600,
    rating_after: 1608,
  },
  {
    game_id: '2',
    game_date: '2024-10-24',
    season: 2024,
    team_abbr: 'DEN',
    opponent_abbr: 'OKC',
    won: false,
    rating_before: 1608,
    rating_after: 1598,
  },
  {
    game_id: '3',
    game_date: '2025-10-24',
    season: 2025,
    team_abbr: 'DEN',
    opponent_abbr: 'GSW',
    won: true,
    rating_before: 1598,
    rating_after: 1611.5,
  },
]

const line = (season: string, ppg: number): StatLine => ({
  season,
  team_abbr: 'DEN',
  age: 29,
  gp: 70,
  gs: 70,
  mpg: 34.6,
  ppg,
  rpg: 12.4,
  apg: 9.0,
  spg: 1.4,
  bpg: 0.9,
  tpg: 3.0,
  fg_pct: 0.583,
  fg3_pct: 0.359,
  ft_pct: 0.817,
  efg_pct: 0.611,
  ts_pct: 0.65,
})

export const CAREER: PlayerCareer = {
  regular_season: { seasons: [line('2023-24', 26.4), line('2024-25', 29.6)], career: line('Career', 21.0) },
  playoffs: { seasons: [], career: null },
}

export const SEARCH_RESULTS: PlayerSearchResult[] = [
  {
    player_id: 203999,
    player_name: 'Nikola Jokić',
    rating: 1712.4,
    peak_rating: 1755.2,
    games: 900,
    team_abbr: 'DEN',
    first_game_date: '2015-10-28',
    last_game_date: '2026-06-01',
    last_season: 2025,
  },
]

export const LEADERBOARD: LeaderboardEntry[] = [
  { rank: 1, ...pick(PLAYER) },
  {
    rank: 2,
    player_id: 1628983,
    player_name: 'Shai Gilgeous-Alexander',
    rating: 1700.1,
    peak_rating: 1720,
    peak_date: '2025-06-01',
    games: 600,
    team_abbr: 'OKC',
    first_game_date: '2018-10-17',
    last_game_date: '2026-06-15',
    last_season: 2025,
  },
]

function pick(p: PlayerRating): Omit<LeaderboardEntry, 'rank'> {
  return {
    player_id: p.player_id,
    player_name: p.player_name,
    rating: p.rating,
    peak_rating: p.peak_rating,
    peak_date: p.peak_date,
    games: p.games,
    team_abbr: p.team_abbr,
    first_game_date: p.first_game_date,
    last_game_date: p.last_game_date,
    last_season: p.last_season,
  }
}
