/** Parses a route param into a positive NBA player id, or null if it isn't one. */
export function parsePlayerId(raw: string | undefined): number | null {
  if (!raw || !/^\d{1,8}$/.test(raw)) return null
  const id = Number(raw)
  return id > 0 ? id : null
}
