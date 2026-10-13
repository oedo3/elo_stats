import type {
  ApiEnvelope,
  EloPoint,
  LeaderboardEntry,
  LeaderboardParams,
  Meta,
  PlayerBio,
  PlayerCareer,
  PlayerRating,
  PlayerSearchResult,
} from './types'

const API_BASE = (import.meta.env.VITE_API_BASE_URL ?? '').replace(/\/$/, '')

export class ApiError extends Error {
  readonly status: number

  constructor(message: string, status: number) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

async function request<T>(path: string, signal?: AbortSignal): Promise<T> {
  let response: Response
  try {
    response = await fetch(`${API_BASE}${path}`, { signal, headers: { Accept: 'application/json' } })
  } catch (err) {
    if (err instanceof DOMException && err.name === 'AbortError') throw err
    throw new ApiError('Cannot reach the ELO Stats server. Is the backend running?', 0)
  }

  let body: ApiEnvelope<T> | null = null
  try {
    body = (await response.json()) as ApiEnvelope<T>
  } catch {
    // Non-JSON body (e.g. proxy error page); handled below.
  }

  if (!response.ok || !body?.success || body.data === null) {
    const message = body?.error ?? `Request failed (${response.status})`
    throw new ApiError(message, response.status)
  }
  return body.data
}

export const api = {
  meta: (signal?: AbortSignal) => request<Meta>('/api/meta', signal),

  searchPlayers: (query: string, signal?: AbortSignal) =>
    request<PlayerSearchResult[]>(
      `/api/players/search?${new URLSearchParams({ q: query, limit: '8' })}`,
      signal,
    ),

  player: (id: number, signal?: AbortSignal) =>
    request<PlayerRating>(`/api/players/${id}`, signal),

  eloHistory: (id: number, signal?: AbortSignal) =>
    request<EloPoint[]>(`/api/players/${id}/elo`, signal),

  bio: (id: number, signal?: AbortSignal) => request<PlayerBio>(`/api/players/${id}/bio`, signal),

  career: (id: number, signal?: AbortSignal) =>
    request<PlayerCareer>(`/api/players/${id}/career`, signal),

  leaderboard: (params: LeaderboardParams, signal?: AbortSignal) => {
    const query = new URLSearchParams({
      sort: params.sort,
      active_only: String(params.activeOnly),
      min_games: String(params.minGames ?? 82),
      limit: String(params.limit ?? 25),
    })
    return request<LeaderboardEntry[]>(`/api/leaderboard?${query}`, signal)
  },
}
