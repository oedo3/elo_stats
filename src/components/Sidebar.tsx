import { useIsFetching, useQueryClient } from '@tanstack/react-query'
import { NavLink } from 'react-router'
import { useMeta } from '../api/hooks'
import type { ThemePreference } from '../hooks/useTheme'
import { formatDate, seasonLabel } from '../lib/format'

const THEME_LABEL: Record<ThemePreference, string> = {
  system: 'Theme: system',
  light: 'Theme: light',
  dark: 'Theme: dark',
}

interface SidebarProps {
  theme: ThemePreference
  onCycleTheme: () => void
}

export function Sidebar({ theme, onCycleTheme }: SidebarProps) {
  const queryClient = useQueryClient()
  const fetching = useIsFetching() > 0
  const { data: meta } = useMeta()

  return (
    <aside className="sidebar">
      <button
        type="button"
        className={`icon-button refresh${fetching ? ' refresh--spinning' : ''}`}
        onClick={() => queryClient.invalidateQueries()}
        aria-label="Refresh data"
        title="Refresh data"
      >
        <svg viewBox="0 0 24 24" width="22" height="22" aria-hidden="true">
          <path
            d="M20 12a8 8 0 1 1-2.34-5.66M20 4v5h-5"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </svg>
      </button>

      <div className="sidebar__date">
        <span className="sidebar__label">Data through</span>
        <span>{formatDate(meta?.last_game_date)}</span>
        {meta?.first_season != null && meta.last_season != null && (
          <span className="sidebar__muted">
            {seasonLabel(meta.first_season)} – {seasonLabel(meta.last_season)}
          </span>
        )}
        {meta && meta.missing_seasons.length > 0 && (
          <span
            className="sidebar__warning"
            role="note"
            title={`Not downloaded yet: ${meta.missing_seasons.join(', ')}`}
          >
            {meta.missing_seasons.length} season download
            {meta.missing_seasons.length === 1 ? '' : 's'} missing. Ratings are provisional.
          </span>
        )}
      </div>

      <nav className="sidebar__nav" aria-label="Main">
        <NavLink to="/" end>
          Leaderboard
        </NavLink>
        <NavLink to="/about">How it works</NavLink>
      </nav>

      <button
        type="button"
        className="button button--ghost sidebar__theme"
        onClick={onCycleTheme}
        title="Switch theme"
      >
        {THEME_LABEL[theme]}
      </button>
    </aside>
  )
}
