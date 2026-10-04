import { describe, expect, it } from 'vitest'
import { HISTORY } from '../test/utils'
import { axisTicks, filterRange, formatTick, summarize, toSeries } from './eloSeries'
import { errorMessage } from './errors'
import {
  draftLabel,
  formatAvg,
  formatDate,
  formatPct,
  formatRating,
  formatSignedDelta,
  initials,
  seasonLabel,
} from './format'
import { parsePlayerId } from './playerId'

describe('format', () => {
  it('formats ISO dates without timezone drift', () => {
    expect(formatDate('2024-01-01')).toBe('Jan 1, 2024')
    expect(formatDate('2024-01-01T23:59:00')).toBe('Jan 1, 2024')
  })

  it('handles missing or bad dates', () => {
    expect(formatDate(null)).toBe('—')
    expect(formatDate('not a date')).toBe('—')
  })

  it('formats numbers', () => {
    expect(formatRating(1712.6)).toBe('1713')
    expect(formatRating(null)).toBe('—')
    expect(formatPct(0.5834)).toBe('58.3')
    expect(formatPct(null)).toBe('—')
    expect(formatAvg(7)).toBe('7.0')
  })

  it('formats signed deltas', () => {
    expect(formatSignedDelta(12.34)).toBe('+12.3')
    expect(formatSignedDelta(-4)).toBe('-4.0')
    expect(formatSignedDelta(0.01)).toBe('±0')
  })

  it('builds season labels across the century', () => {
    expect(seasonLabel(1999)).toBe('1999-00')
    expect(seasonLabel(2025)).toBe('2025-26')
  })

  it('builds initials and draft labels', () => {
    expect(initials('Shai Gilgeous-Alexander')).toBe('SG')
    expect(initials('  nene  ')).toBe('N')
    expect(draftLabel(2014, 2, 41)).toBe('2014 · R2, #41')
    expect(draftLabel(2014, null, null)).toBe('2014 · Undrafted')
    expect(draftLabel(null, null, null)).toBe('—')
  })
})

describe('parsePlayerId', () => {
  it.each([
    ['203999', 203999],
    ['0', null],
    ['-5', null],
    ['12abc', null],
    ['123456789', null],
    [undefined, null],
  ])('%s -> %s', (raw, expected) => {
    expect(parsePlayerId(raw)).toBe(expected)
  })
})

describe('errorMessage', () => {
  it('uses Error messages and falls back otherwise', () => {
    expect(errorMessage(new Error('nope'))).toBe('nope')
    expect(errorMessage('weird')).toBe('Something went wrong.')
    expect(errorMessage(undefined, 'fallback')).toBe('fallback')
  })
})

describe('eloSeries', () => {
  it('filters to recent seasons', () => {
    expect(filterRange(HISTORY, 'career')).toHaveLength(3)
    expect(filterRange(HISTORY, 'latest').map((p) => p.season)).toEqual([2025])
    expect(filterRange(HISTORY, 'last3')).toHaveLength(3)
    expect(filterRange([], 'latest')).toEqual([])
  })

  it('converts to chart points with deltas', () => {
    const series = toSeries(HISTORY)
    expect(series[1]).toMatchObject({ rating: 1598, delta: -10, opponent: 'OKC', won: false })
    expect(series[0]?.time).toBe(Date.UTC(2023, 9, 24))
  })

  it('summarizes record, change and extremes', () => {
    const summary = summarize(toSeries(HISTORY))
    expect(summary).toMatchObject({ games: 3, wins: 2, losses: 1, start: 1600, end: 1611.5 })
    expect(summary?.peak).toBe(1611.5)
    expect(summary?.low).toBe(1598)
    expect(summary?.bestGame?.opponent).toBe('GSW')
    expect(summary?.worstGame?.opponent).toBe('OKC')
  })

  it('uses one tick per year for multi-season ranges', () => {
    const { ticks, unit } = axisTicks(toSeries(HISTORY))
    expect(unit).toBe('year')
    expect(ticks).toEqual([Date.UTC(2024, 0, 1), Date.UTC(2025, 0, 1)])
    expect(formatTick(ticks[0] ?? 0, unit)).toBe('2024')
  })

  it('uses month ticks within a season', () => {
    const season = toSeries([
      { ...HISTORY[0]!, game_date: '2025-10-22' },
      { ...HISTORY[1]!, game_date: '2026-04-12' },
    ])
    const { ticks, unit } = axisTicks(season)
    expect(unit).toBe('month')
    expect(ticks[0]).toBe(Date.UTC(2025, 10, 1))
    expect(formatTick(ticks[0] ?? 0, unit)).toBe('Nov 25')
    expect(axisTicks([])).toEqual({ ticks: [], unit: 'year' })
  })

  it('returns null for empty series', () => {
    expect(summarize([])).toBeNull()
  })
})
