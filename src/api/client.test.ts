import { afterEach, describe, expect, it, vi } from 'vitest'
import { envelope, mockFetch } from '../test/utils'
import { ApiError, api } from './client'
import { shouldRetry } from './hooks'

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('api client', () => {
  it('unwraps the success envelope', async () => {
    mockFetch(() => ({ body: envelope({ has_data: true }) }))
    await expect(api.meta()).resolves.toEqual({ has_data: true })
  })

  it('builds query strings safely', async () => {
    const fetchMock = mockFetch(() => ({ body: envelope([]) }))
    await api.searchPlayers('a&b=c')
    await api.leaderboard({ sort: 'peak', activeOnly: false })
    const urls = fetchMock.mock.calls.map(([input]) => String(input))
    expect(urls[0]).toBe('/api/players/search?q=a%26b%3Dc&limit=8')
    expect(urls[1]).toBe('/api/leaderboard?sort=peak&active_only=false&min_games=82&limit=25')
  })

  it('surfaces server error messages with status', async () => {
    mockFetch(() => ({
      status: 503,
      body: { success: false, data: null, error: 'No Elo data yet.', meta: null },
    }))
    const error = await api.player(1).catch((e: unknown) => e)
    expect(error).toBeInstanceOf(ApiError)
    expect(error).toMatchObject({ status: 503, message: 'No Elo data yet.' })
  })

  it('explains network failures', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('Failed to fetch')))
    await expect(api.meta()).rejects.toMatchObject({ status: 0, message: expect.stringMatching(/backend/) })
  })

  it('rethrows aborts untouched', async () => {
    const abort = new DOMException('aborted', 'AbortError')
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(abort))
    await expect(api.meta()).rejects.toBe(abort)
  })

  it('handles non-JSON error bodies', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('<html>Bad gateway</html>', { status: 502 })))
    await expect(api.meta()).rejects.toMatchObject({ status: 502, message: 'Request failed (502)' })
  })
})

describe('shouldRetry', () => {
  it('does not retry client errors or the no-data 503', () => {
    expect(shouldRetry(0, new ApiError('nope', 404))).toBe(false)
    expect(shouldRetry(0, new ApiError('no data', 503))).toBe(false)
  })

  it('retries network and 5xx errors twice', () => {
    expect(shouldRetry(0, new ApiError('down', 502))).toBe(true)
    expect(shouldRetry(1, new ApiError('offline', 0))).toBe(true)
    expect(shouldRetry(2, new ApiError('offline', 0))).toBe(false)
  })
})
