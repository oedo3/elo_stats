import { Link, Outlet } from 'react-router'
import { useTheme } from '../hooks/useTheme'
import { PlayerSearch } from './PlayerSearch'
import { Sidebar } from './Sidebar'

export function Layout() {
  const { theme, cycleTheme } = useTheme()

  return (
    <div className="app">
      <Sidebar theme={theme} onCycleTheme={cycleTheme} />
      <div className="main">
        <header className="header">
          <Link to="/" className="header__title">
            ELO Stats
          </Link>
          <span className="header__tagline">Game-by-game NBA player Elo</span>
        </header>
        <PlayerSearch />
        <main className="content">
          <Outlet />
        </main>
      </div>
    </div>
  )
}
