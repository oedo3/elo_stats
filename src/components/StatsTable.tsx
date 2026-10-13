import { useState } from 'react'
import type { PlayerCareer, StatLine } from '../api/types'
import { formatAvg, formatPct } from '../lib/format'

type Split = 'regular_season' | 'playoffs'

const SPLITS: { key: Split; label: string }[] = [
  { key: 'regular_season', label: 'Regular season' },
  { key: 'playoffs', label: 'Playoffs' },
]

interface Column {
  label: string
  title: string
  render: (line: StatLine) => string
}

const COLUMNS: Column[] = [
  { label: 'Team', title: 'Team', render: (l) => l.team_abbr ?? '' },
  { label: 'Age', title: 'Age', render: (l) => (l.age == null ? '' : String(Math.floor(l.age))) },
  { label: 'G', title: 'Games played', render: (l) => String(l.gp) },
  { label: 'MIN', title: 'Minutes per game', render: (l) => formatAvg(l.mpg) },
  { label: 'PTS', title: 'Points per game', render: (l) => formatAvg(l.ppg) },
  { label: 'TRB', title: 'Rebounds per game', render: (l) => formatAvg(l.rpg) },
  { label: 'AST', title: 'Assists per game', render: (l) => formatAvg(l.apg) },
  { label: 'STL', title: 'Steals per game', render: (l) => formatAvg(l.spg) },
  { label: 'BLK', title: 'Blocks per game', render: (l) => formatAvg(l.bpg) },
  { label: 'FG%', title: 'Field goal %', render: (l) => formatPct(l.fg_pct) },
  { label: '3P%', title: 'Three-point %', render: (l) => formatPct(l.fg3_pct) },
  { label: 'FT%', title: 'Free throw %', render: (l) => formatPct(l.ft_pct) },
  { label: 'eFG%', title: 'Effective field goal %', render: (l) => formatPct(l.efg_pct) },
  { label: 'TS%', title: 'True shooting %', render: (l) => formatPct(l.ts_pct) },
]

export function StatsTable({ career }: { career: PlayerCareer }) {
  const [split, setSplit] = useState<Split>('regular_season')
  const { seasons, career: totals } = career[split]

  return (
    <section className="card" aria-labelledby="stats-heading">
      <div className="card__header">
        <h2 id="stats-heading">Per-game stats</h2>
        <div className="segmented" role="group" aria-label="Season type">
          {SPLITS.map(({ key, label }) => (
            <button
              key={key}
              type="button"
              aria-pressed={split === key}
              onClick={() => setSplit(key)}
            >
              {label}
            </button>
          ))}
        </div>
      </div>

      {seasons.length === 0 ? (
        <p className="muted">No {split === 'playoffs' ? 'playoff' : 'regular season'} games.</p>
      ) : (
        <div className="table-scroll">
          <table className="table table--stats">
            <thead>
              <tr>
                <th scope="col">Season</th>
                {COLUMNS.map((c) => (
                  <th key={c.label} scope="col" title={c.title}>
                    {c.label}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {seasons.map((line, i) => (
                <tr key={`${line.season}-${line.team_abbr}-${i}`}>
                  <th scope="row">{line.season}</th>
                  {COLUMNS.map((c) => (
                    <td key={c.label}>{c.render(line)}</td>
                  ))}
                </tr>
              ))}
            </tbody>
            {totals && (
              <tfoot>
                <tr>
                  <th scope="row">Career</th>
                  {COLUMNS.map((c) => (
                    <td key={c.label}>{c.label === 'Team' || c.label === 'Age' ? '' : c.render(totals)}</td>
                  ))}
                </tr>
              </tfoot>
            )}
          </table>
        </div>
      )}
    </section>
  )
}
