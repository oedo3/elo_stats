// Mirrors backend/src/elo_stats/schemas.py

export interface ApiEnvelope<T> {
  success: boolean
  data: T | null
  error: string | null
  meta: Record<string, unknown> | null
}

export interface Meta {
  has_data: boolean
  first_season: number | null
  last_season: number | null
  last_game_date: string | null
  computed_at: string | null
  elo_params: Record<string, number> | null
  missing_seasons: string[]
}

export interface PlayerSearchResult {
  player_id: number
  player_name: string
  rating: number
  peak_rating: number
  games: number
  team_abbr: string
  first_game_date: string
  last_game_date: string
  last_season: number
}

export interface PlayerRating {
  player_id: number
  player_name: string
  rating: number
  peak_rating: number
  peak_date: string
  games: number
  first_game_date: string
  last_game_date: string
  last_season: number
  team_abbr: string
  is_active: boolean
  active_rank: number | null
  peak_rank: number
}

export interface EloPoint {
  game_id: string
  game_date: string
  season: number
  team_abbr: string
  opponent_abbr: string
  won: boolean
  rating_before: number
  rating_after: number
}

export interface LeaderboardEntry {
  rank: number
  player_id: number
  player_name: string
  rating: number
  peak_rating: number
  peak_date: string
  games: number
  team_abbr: string
  first_game_date: string
  last_game_date: string
  last_season: number
}

export type LeaderboardSort = 'current' | 'peak'

export interface LeaderboardParams {
  sort: LeaderboardSort
  activeOnly: boolean
  minGames?: number
  limit?: number
}

export interface PlayerBio {
  player_id: number
  name: string | null
  position: string | null
  height: string | null
  weight: number | null
  jersey: string | null
  birthdate: string | null
  country: string | null
  school: string | null
  team_name: string | null
  team_abbr: string | null
  draft_year: number | null
  draft_round: number | null
  draft_number: number | null
  from_year: number | null
  to_year: number | null
  seasons: number | null
  is_active: boolean
  greatest_75: boolean
}

export interface StatLine {
  season: string
  team_abbr: string | null
  age: number | null
  gp: number
  gs: number | null
  mpg: number | null
  ppg: number | null
  rpg: number | null
  apg: number | null
  spg: number | null
  bpg: number | null
  tpg: number | null
  fg_pct: number | null
  fg3_pct: number | null
  ft_pct: number | null
  efg_pct: number | null
  ts_pct: number | null
}

export interface CareerSplit {
  seasons: StatLine[]
  career: StatLine | null
}

export interface PlayerCareer {
  regular_season: CareerSplit
  playoffs: CareerSplit
}
