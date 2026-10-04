import type { EloPoint } from '../api/types'

export type EloRange = 'career' | 'last3' | 'latest'

export const RANGE_LABELS: Record<EloRange, string> = {
  career: 'Career',
  last3: 'Last 3 seasons',
  latest: 'Latest season',
}

export interface SeriesPoint {
  time: number
  date: string
  rating: number
  delta: number
  opponent: string
  team: string
  won: boolean
  season: number
}

export interface EloSummary {
  games: number
  wins: number
  losses: number
  start: number
  end: number
  peak: number
  low: number
  bestGame: SeriesPoint | null
  worstGame: SeriesPoint | null
}

export function filterRange(history: readonly EloPoint[], range: EloRange): EloPoint[] {
  if (range === 'career' || history.length === 0) return [...history]
  const lastSeason = history[history.length - 1]?.season ?? 0
  const firstIncluded = range === 'latest' ? lastSeason : lastSeason - 2
  return history.filter((point) => point.season >= firstIncluded)
}

export function toSeries(history: readonly EloPoint[]): SeriesPoint[] {
  return history.map((point) => ({
    time: Date.parse(`${point.game_date}T00:00:00Z`),
    date: point.game_date,
    rating: Math.round(point.rating_after * 10) / 10,
    delta: point.rating_after - point.rating_before,
    opponent: point.opponent_abbr,
    team: point.team_abbr,
    won: point.won,
    season: point.season,
  }))
}

export type TickUnit = 'year' | 'month'

/** Evenly spaced Jan-1 ticks for multi-year ranges, or month ticks for a single season. */
export function axisTicks(series: readonly SeriesPoint[]): { ticks: number[]; unit: TickUnit } {
  const first = series[0]
  const last = series[series.length - 1]
  if (!first || !last) return { ticks: [], unit: 'year' }

  const start = new Date(first.time)
  const end = new Date(last.time)
  const years: number[] = []
  for (let y = start.getUTCFullYear() + 1; y <= end.getUTCFullYear(); y += 1) {
    years.push(Date.UTC(y, 0, 1))
  }
  if (years.length >= 2) {
    const step = Math.ceil(years.length / 10)
    return { ticks: years.filter((_, i) => i % step === 0), unit: 'year' }
  }

  const months: number[] = []
  const cursor = new Date(Date.UTC(start.getUTCFullYear(), start.getUTCMonth() + 1, 1))
  while (cursor.getTime() <= last.time) {
    months.push(cursor.getTime())
    cursor.setUTCMonth(cursor.getUTCMonth() + 1)
  }
  const step = Math.ceil(months.length / 8) || 1
  return { ticks: months.filter((_, i) => i % step === 0), unit: 'month' }
}

const monthFormatter = new Intl.DateTimeFormat('en-US', { month: 'short', year: '2-digit', timeZone: 'UTC' })

export function formatTick(time: number, unit: TickUnit): string {
  return unit === 'year' ? String(new Date(time).getUTCFullYear()) : monthFormatter.format(time)
}

export function summarize(series: readonly SeriesPoint[]): EloSummary | null {
  const first = series[0]
  const last = series[series.length - 1]
  if (!first || !last) return null

  let peak = first.rating
  let low = first.rating
  let best = first
  let worst = first
  let wins = 0
  for (const point of series) {
    peak = Math.max(peak, point.rating)
    low = Math.min(low, point.rating)
    if (point.delta > best.delta) best = point
    if (point.delta < worst.delta) worst = point
    if (point.won) wins += 1
  }

  return {
    games: series.length,
    wins,
    losses: series.length - wins,
    start: first.rating - first.delta,
    end: last.rating,
    peak,
    low,
    bestGame: best,
    worstGame: worst,
  }
}
