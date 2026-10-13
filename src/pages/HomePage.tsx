import { useState } from 'react'
import { Link } from 'react-router'
import { useLeaderboard } from '../api/hooks'
import type { LeaderboardSort } from '../api/types'
import { StatusMessage } from '../components/StatusMessage'
import { formatDate, formatRating } from '../lib/format'

export function HomePage() {
  const [sort, setSort] = useState<LeaderboardSort>('current')
  const [activeOnly, setActiveOnly] = useState(true)
  const { data, isPending, isError, error, refetch, isPlaceholderData } = useLeaderboard({
    sort,
    activeOnly,
  })

  return (
    <section className="card" aria-labelledby="leaderboard-heading">
      <div className="card__header">
        <h1 id="leaderboard-heading">
          {sort === 'peak' ? 'Highest peaks' : activeOnly ? 'Top rated now' : 'Best final ratings'}
        </h1>
        <div className="controls">
          <div className="segmented" role="group" aria-label="Sort by">
            <button type="button" aria-pressed={sort === 'current'} onClick={() => setSort('current')}>
              Current Elo
            </button>
            <button type="button" aria-pressed={sort === 'peak'} onClick={() => setSort('peak')}>
              Peak Elo
            </button>
          </div>
          <label className="checkbox">
            <input
              type="checkbox"
              checked={activeOnly}
              onChange={(event) => setActiveOnly(event.target.checked)}
            />
            Active players only
          </label>
        </div>
      </div>

      {isPending && <StatusMessage kind="loading" message="Loading leaderboard…" />}
      {isError && <StatusMessage kind="error" error={error} onRetry={() => refetch()} />}
      {data && data.length === 0 && <StatusMessage kind="empty" message="No players match." />}
      {data && data.length > 0 && (
        <div className={`table-scroll${isPlaceholderData ? ' is-stale' : ''}`}>
          <table className="table">
            <thead>
              <tr>
                <th scope="col">#</th>
                <th scope="col">Player</th>
                <th scope="col">Team</th>
                <th scope="col" className="num">
                  Elo
                </th>
                <th scope="col" className="num">
                  Peak
                </th>
                <th scope="col" className="hide-sm">
                  Peak date
                </th>
                <th scope="col" className="num hide-sm">
                  Games
                </th>
              </tr>
            </thead>
            <tbody>
              {data.map((row) => (
                <tr key={row.player_id}>
                  <td>{row.rank}</td>
                  <th scope="row">
                    <Link to={`/players/${row.player_id}`}>{row.player_name}</Link>
                  </th>
                  <td>{row.team_abbr}</td>
                  <td className="num strong">{formatRating(row.rating)}</td>
                  <td className="num">{formatRating(row.peak_rating)}</td>
                  <td className="hide-sm">{formatDate(row.peak_date)}</td>
                  <td className="num hide-sm">{row.games}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  )
}
