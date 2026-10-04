const dateFormatter = new Intl.DateTimeFormat('en-US', {
  year: 'numeric',
  month: 'short',
  day: 'numeric',
  timeZone: 'UTC',
})

/** Formats an ISO date (YYYY-MM-DD) without shifting it into the viewer's timezone. */
export function formatDate(isoDate: string | null | undefined): string {
  if (!isoDate) return '—'
  const parsed = new Date(`${isoDate.slice(0, 10)}T00:00:00Z`)
  return Number.isNaN(parsed.getTime()) ? '—' : dateFormatter.format(parsed)
}

export function formatRating(rating: number | null | undefined): string {
  return rating == null ? '—' : Math.round(rating).toString()
}

export function formatSignedDelta(delta: number): string {
  const rounded = Math.round(delta * 10) / 10
  if (rounded === 0) return '±0'
  return `${rounded > 0 ? '+' : ''}${rounded.toFixed(1)}`
}

export function formatPct(value: number | null | undefined): string {
  return value == null ? '—' : `${(value * 100).toFixed(1)}`
}

export function formatAvg(value: number | null | undefined): string {
  return value == null ? '—' : value.toFixed(1)
}

export function seasonLabel(startYear: number): string {
  return `${startYear}-${String((startYear + 1) % 100).padStart(2, '0')}`
}

export function initials(name: string): string {
  return name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0]?.toUpperCase() ?? '')
    .join('')
}

export function headshotUrl(playerId: number): string {
  return `https://cdn.nba.com/headshots/nba/latest/260x190/${playerId}.png`
}

export function draftLabel(year: number | null, round: number | null, pick: number | null): string {
  if (year == null) return '—'
  if (round == null || pick == null) return `${year} · Undrafted`
  return `${year} · R${round}, #${pick}`
}
