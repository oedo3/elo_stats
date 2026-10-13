import { keepPreviousData, queryOptions, useQuery } from '@tanstack/react-query'
import { ApiError, api } from './client'
import type { LeaderboardParams } from './types'

const FIVE_MINUTES = 5 * 60 * 1000

export const queryKeys = {
  meta: ['meta'] as const,
  search: (q: string) => ['search', q] as const,
  player: (id: number) => ['player', id] as const,
  elo: (id: number) => ['player', id, 'elo'] as const,
  bio: (id: number) => ['player', id, 'bio'] as const,
  career: (id: number) => ['player', id, 'career'] as const,
  leaderboard: (p: LeaderboardParams) => ['leaderboard', p] as const,
}

/** Don't retry errors the server meant (404, 422, 503 no-data); do retry network/5xx blips. */
export function shouldRetry(failureCount: number, error: unknown): boolean {
  if (error instanceof ApiError && error.status >= 400 && error.status < 500) return false
  if (error instanceof ApiError && error.status === 503) return false
  return failureCount < 2
}

export const useMeta = () =>
  useQuery({ queryKey: queryKeys.meta, queryFn: ({ signal }) => api.meta(signal), staleTime: FIVE_MINUTES })

export const searchQuery = (query: string) =>
  queryOptions({
    queryKey: queryKeys.search(query),
    queryFn: ({ signal }) => api.searchPlayers(query, signal),
    staleTime: FIVE_MINUTES,
  })

export const usePlayerSearch = (query: string) =>
  useQuery({
    ...searchQuery(query),
    enabled: query.length >= 2,
    placeholderData: keepPreviousData,
  })

export const usePlayer = (id: number) =>
  useQuery({ queryKey: queryKeys.player(id), queryFn: ({ signal }) => api.player(id, signal) })

export const useEloHistory = (id: number) =>
  useQuery({ queryKey: queryKeys.elo(id), queryFn: ({ signal }) => api.eloHistory(id, signal) })

export const usePlayerBio = (id: number) =>
  useQuery({
    queryKey: queryKeys.bio(id),
    queryFn: ({ signal }) => api.bio(id, signal),
    staleTime: FIVE_MINUTES,
  })

export const usePlayerCareer = (id: number) =>
  useQuery({
    queryKey: queryKeys.career(id),
    queryFn: ({ signal }) => api.career(id, signal),
    staleTime: FIVE_MINUTES,
  })

export const useLeaderboard = (params: LeaderboardParams) =>
  useQuery({
    queryKey: queryKeys.leaderboard(params),
    queryFn: ({ signal }) => api.leaderboard(params, signal),
    placeholderData: keepPreviousData,
  })
