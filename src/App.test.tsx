import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { AppRoutes } from './App'
import {
  BIO,
  CAREER,
  HISTORY,
  LEADERBOARD,
  META,
  PLAYER,
  SEARCH_RESULTS,
  envelope,
  mockFetch,
  renderWithProviders,
} from './test/utils'

type Overrides = Partial<Record<'bio' | 'leaderboard', { status: number; body: unknown }>>

function mockApi(overrides: Overrides = {}) {
  return mockFetch((url) => {
    const path = url.pathname
    if (path === '/api/meta') return { body: envelope(META) }
    if (path === '/api/leaderboard') return overrides.leaderboard ?? { body: envelope(LEADERBOARD) }
    if (path === '/api/players/search') return { body: envelope(SEARCH_RESULTS) }
    if (path === '/api/players/203999') return { body: envelope(PLAYER) }
    if (path === '/api/players/203999/elo') return { body: envelope(HISTORY) }
    if (path === '/api/players/203999/bio') return overrides.bio ?? { body: envelope(BIO) }
    if (path === '/api/players/203999/career') return { body: envelope(CAREER) }
    return undefined
  })
}

beforeEach(() => {
  window.localStorage.clear()
  document.documentElement.removeAttribute('data-theme')
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('home page', () => {
  it('shows the leaderboard and the data date', async () => {
    mockApi()
    renderWithProviders(<AppRoutes />)
    const table = await screen.findByRole('table')
    expect(within(table).getByRole('link', { name: 'Nikola Jokić' })).toHaveAttribute(
      'href',
      '/players/203999',
    )
    expect(within(table).getByText('1712')).toBeInTheDocument()
    expect(await screen.findByText('Jun 15, 2026')).toBeInTheDocument()
  })

  it('switches to peak sort and toggles active filter', async () => {
    const fetchMock = mockApi()
    renderWithProviders(<AppRoutes />)
    await screen.findByRole('table')
    await userEvent.click(screen.getByRole('button', { name: 'Peak Elo' }))
    await userEvent.click(screen.getByRole('checkbox', { name: /active players only/i }))
    await waitFor(() => {
      const urls = fetchMock.mock.calls.map(([input]) => String(input))
      expect(urls).toContain('/api/leaderboard?sort=peak&active_only=false&min_games=82&limit=25')
    })
    expect(screen.getByRole('heading', { name: 'Highest peaks' })).toBeInTheDocument()
  })

  it('shows the no-data message from the server', async () => {
    mockApi({
      leaderboard: {
        status: 503,
        body: { success: false, data: null, error: 'No Elo data yet. Run ingest.', meta: null },
      },
    })
    renderWithProviders(<AppRoutes />)
    expect(await screen.findByRole('alert')).toHaveTextContent('No Elo data yet. Run ingest.')
  })
})

describe('player search', () => {
  it('suggests players and navigates on selection', async () => {
    mockApi()
    renderWithProviders(<AppRoutes />)
    const input = screen.getByRole('combobox', { name: /search for a player/i })
    await userEvent.type(input, 'jok')
    const option = await screen.findByRole('option', { name: /Nikola Jokić/ })
    await userEvent.click(option)
    expect(await screen.findByRole('heading', { level: 1, name: /Nikola Jokić/ })).toBeInTheDocument()
  })

  it('submits to the first match with Enter', async () => {
    mockApi()
    renderWithProviders(<AppRoutes />)
    const input = screen.getByRole('combobox', { name: /search for a player/i })
    await userEvent.type(input, 'nikola')
    await screen.findByRole('option', { name: /Nikola Jokić/ })
    await userEvent.type(input, '{arrowdown}{enter}')
    expect(await screen.findByRole('heading', { level: 1, name: /Nikola Jokić/ })).toBeInTheDocument()
  })
})

describe('player search (stale results)', () => {
  it('waits for fresh results when Enter is pressed immediately', async () => {
    mockApi()
    renderWithProviders(<AppRoutes />)
    const input = screen.getByRole('combobox', { name: /search for a player/i })
    await userEvent.type(input, 'nikola{enter}')
    expect(await screen.findByRole('heading', { level: 1, name: /Nikola Jokić/ })).toBeInTheDocument()
  })

  it('ignores Enter until results match the typed text', async () => {
    mockApi()
    renderWithProviders(<AppRoutes />)
    const input = screen.getByRole('combobox', { name: /search for a player/i })
    await userEvent.type(input, 'nikola')
    await screen.findByRole('option', { name: /Nikola Jokić/ })
    await userEvent.clear(input)
    await userEvent.type(input, 'x{enter}')
    expect(screen.queryByRole('heading', { level: 1, name: /Nikola Jokić/ })).not.toBeInTheDocument()
  })
})

describe('player page', () => {
  it('renders profile, Elo summary and stats', async () => {
    mockApi()
    renderWithProviders(<AppRoutes />, { route: '/players/203999' })
    expect(await screen.findByRole('heading', { level: 1, name: /Nikola Jokić/ })).toBeInTheDocument()
    expect(screen.getByText('#1 among active players')).toBeInTheDocument()
    expect(await screen.findByText('Center')).toBeInTheDocument()
    expect(screen.getByLabelText('Jersey number 15')).toBeInTheDocument()
    expect(await screen.findByText('2014 · R2, #41')).toBeInTheDocument()

    const eloSection = await screen.findByRole('region', { name: 'Elo history' })
    expect(within(eloSection).getByText('+11.5')).toBeInTheDocument()

    const stats = await screen.findByRole('region', { name: 'Per-game stats' })
    expect(within(stats).getByText('29.6')).toBeInTheDocument()
    await userEvent.click(within(stats).getByRole('button', { name: 'Playoffs' }))
    expect(within(stats).getByText('No playoff games.')).toBeInTheDocument()
  })

  it('changes the chart range', async () => {
    mockApi()
    renderWithProviders(<AppRoutes />, { route: '/players/203999' })
    const eloSection = await screen.findByRole('region', { name: 'Elo history' })
    await userEvent.click(within(eloSection).getByRole('button', { name: 'Latest season' }))
    expect(within(eloSection).getByRole('img', { name: 'Elo rating over 1 game' })).toBeInTheDocument()
    expect(within(eloSection).getAllByText('+13.5')).toHaveLength(2)
    expect(within(eloSection).getByRole('button', { name: 'Latest season' })).toHaveAttribute(
      'aria-pressed',
      'true',
    )
  })

  it('still shows Elo when the bio service is down', async () => {
    mockApi({
      bio: {
        status: 502,
        body: { success: false, data: null, error: 'NBA stats unavailable', meta: null },
      },
    })
    renderWithProviders(<AppRoutes />, { route: '/players/203999' })
    expect(await screen.findByText('Bio details are unavailable right now.')).toBeInTheDocument()
    expect(screen.getByText('1712')).toBeInTheDocument()
  })

  it('reports unknown players and bad links', async () => {
    mockApi()
    renderWithProviders(<AppRoutes />, { route: '/players/42' })
    expect(await screen.findByRole('alert')).toHaveTextContent('Not found')
  })

  it('rejects malformed ids without calling the API', () => {
    const fetchMock = mockApi()
    renderWithProviders(<AppRoutes />, { route: '/players/abc' })
    expect(screen.getByRole('alert')).toHaveTextContent("That isn't a valid player link.")
    expect(fetchMock.mock.calls.some(([u]) => String(u).includes('/api/players/'))).toBe(false)
  })
})

describe('chrome', () => {
  it('cycles the theme and remembers it', async () => {
    mockApi()
    renderWithProviders(<AppRoutes />)
    const toggle = screen.getByRole('button', { name: 'Theme: system' })
    await userEvent.click(toggle)
    expect(document.documentElement).toHaveAttribute('data-theme', 'light')
    await userEvent.click(screen.getByRole('button', { name: 'Theme: light' }))
    expect(document.documentElement).toHaveAttribute('data-theme', 'dark')
    expect(window.localStorage.getItem('elo-stats-theme')).toBe('dark')
  })

  it('warns when season downloads are missing', async () => {
    mockFetch((url) =>
      url.pathname === '/api/meta'
        ? { body: envelope({ ...META, missing_seasons: ['1996-97 Playoffs', '1997-98 Playoffs'] }) }
        : { body: envelope(LEADERBOARD) },
    )
    renderWithProviders(<AppRoutes />)
    expect(await screen.findByRole('note')).toHaveTextContent('2 season downloads missing')
  })

  it('renders the about page', async () => {
    mockApi()
    renderWithProviders(<AppRoutes />, { route: '/about' })
    expect(await screen.findByRole('heading', { name: 'How the Elo works' })).toBeInTheDocument()
    expect(await screen.findByText(/K = 20/)).toBeInTheDocument()
  })

  it('shows not found for unknown routes', () => {
    mockApi()
    renderWithProviders(<AppRoutes />, { route: '/nope' })
    expect(screen.getByRole('heading', { name: 'Page not found' })).toBeInTheDocument()
  })
})
