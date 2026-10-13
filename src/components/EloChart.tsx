import { useMemo, useState } from 'react'
import {
  CartesianGrid,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
  type TooltipContentProps,
} from 'recharts'
import type { EloPoint } from '../api/types'
import { formatDate, formatRating, formatSignedDelta } from '../lib/format'
import {
  RANGE_LABELS,
  axisTicks,
  filterRange,
  formatTick,
  summarize,
  toSeries,
  type EloRange,
  type SeriesPoint,
} from '../lib/eloSeries'

const BASELINE = 1500
const RANGES = Object.keys(RANGE_LABELS) as EloRange[]

function ChartTooltip({ active, payload }: TooltipContentProps) {
  const point = payload?.[0]?.payload as SeriesPoint | undefined
  if (!active || !point) return null
  return (
    <div className="chart-tooltip">
      <strong>{formatDate(point.date)}</strong>
      <span>
        {point.team} vs {point.opponent} · {point.won ? 'W' : 'L'}
      </span>
      <span>
        Elo {formatRating(point.rating)}{' '}
        <span className={point.delta >= 0 ? 'up' : 'down'}>({formatSignedDelta(point.delta)})</span>
      </span>
    </div>
  )
}

export function EloChart({ history }: { history: readonly EloPoint[] }) {
  const [range, setRange] = useState<EloRange>('career')
  const series = useMemo(() => toSeries(filterRange(history, range)), [history, range])
  const summary = useMemo(() => summarize(series), [series])
  const { ticks, unit } = useMemo(() => axisTicks(series), [series])

  if (!summary) return null

  const pad = 25
  const domain: [number, number] = [
    Math.floor((Math.min(summary.low, BASELINE) - pad) / 50) * 50,
    Math.ceil((Math.max(summary.peak, BASELINE) + pad) / 50) * 50,
  ]
  const yStep = domain[1] - domain[0] > 400 ? 100 : 50
  const yTicks = Array.from(
    { length: Math.floor((domain[1] - domain[0]) / yStep) + 1 },
    (_, i) => domain[0] + i * yStep,
  )

  return (
    <section className="card" aria-labelledby="elo-heading">
      <div className="card__header">
        <h2 id="elo-heading">Elo history</h2>
        <div className="segmented" role="group" aria-label="Chart range">
          {RANGES.map((option) => (
            <button
              key={option}
              type="button"
              aria-pressed={range === option}
              onClick={() => setRange(option)}
            >
              {RANGE_LABELS[option]}
            </button>
          ))}
        </div>
      </div>

      <dl className="summary">
        <div>
          <dt>Games</dt>
          <dd>
            {summary.games} <small>({summary.wins}-{summary.losses})</small>
          </dd>
        </div>
        <div>
          <dt>Change</dt>
          <dd className={summary.end >= summary.start ? 'up' : 'down'}>
            {formatSignedDelta(summary.end - summary.start)}
          </dd>
        </div>
        <div>
          <dt>High / Low</dt>
          <dd>
            {formatRating(summary.peak)} / {formatRating(summary.low)}
          </dd>
        </div>
        {summary.bestGame && (
          <div>
            <dt>Best game</dt>
            <dd>
              <span className="up">{formatSignedDelta(summary.bestGame.delta)}</span>{' '}
              <small>
                vs {summary.bestGame.opponent}, {formatDate(summary.bestGame.date)}
              </small>
            </dd>
          </div>
        )}
      </dl>

      <div className="chart" role="img" aria-label={`Elo rating over ${summary.games} game${summary.games === 1 ? '' : 's'}`}>
        <ResponsiveContainer width="100%" height={300}>
          <LineChart data={series} margin={{ top: 8, right: 16, bottom: 0, left: 0 }}>
            <CartesianGrid stroke="var(--grid)" vertical={false} />
            <XAxis
              dataKey="time"
              type="number"
              scale="time"
              domain={['dataMin', 'dataMax']}
              ticks={ticks}
              tickFormatter={(time: number) => formatTick(time, unit)}
              stroke="var(--muted)"
              tick={{ fontSize: 12 }}
            />
            <YAxis domain={domain} ticks={yTicks} stroke="var(--muted)" tick={{ fontSize: 12 }} width={48} />
            <ReferenceLine
              y={BASELINE}
              stroke="var(--muted)"
              strokeDasharray="4 4"
              label={{ value: 'Avg 1500', position: 'insideTopLeft', fill: 'var(--muted)', fontSize: 11 }}
            />
            <Tooltip content={ChartTooltip} />
            <Line
              type="monotone"
              dataKey="rating"
              stroke="var(--accent)"
              strokeWidth={2}
              dot={false}
              isAnimationActive={false}
            />
          </LineChart>
        </ResponsiveContainer>
      </div>
    </section>
  )
}
