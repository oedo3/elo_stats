import { useState } from 'react'
import type { PlayerBio, PlayerRating } from '../api/types'
import { draftLabel, formatDate, formatRating, headshotUrl, initials } from '../lib/format'

interface PlayerProfileProps {
  player: PlayerRating
  bio: PlayerBio | undefined
  bioLoading: boolean
  bioError: boolean
}

function Avatar({ playerId, name }: { playerId: number; name: string }) {
  const [failed, setFailed] = useState(false)
  if (failed) {
    return (
      <div className="avatar avatar--initials" aria-hidden="true">
        {initials(name)}
      </div>
    )
  }
  return (
    <img
      className="avatar"
      src={headshotUrl(playerId)}
      alt=""
      loading="lazy"
      onError={() => setFailed(true)}
    />
  )
}

export function PlayerProfile({ player, bio, bioLoading, bioError }: PlayerProfileProps) {
  const facts: [string, string][] = bio
    ? [
        ['Position', bio.position ?? '—'],
        ['Height', bio.height ?? '—'],
        ['Weight', bio.weight ? `${bio.weight} lb` : '—'],
        ['Team', bio.team_name ?? player.team_abbr],
        ['Draft', draftLabel(bio.draft_year, bio.draft_round, bio.draft_number)],
        ['Born', formatDate(bio.birthdate)],
      ]
    : [['Last team', player.team_abbr]]

  return (
    <section className="card profile" aria-label={`${player.player_name} profile`}>
      <Avatar playerId={player.player_id} name={player.player_name} />

      <div className="profile__info">
        <h1 className="profile__name">
          {player.player_name}
          {bio?.greatest_75 && <span className="badge" title="NBA 75th Anniversary Team">75</span>}
        </h1>
        <p className="muted">
          {formatDate(player.first_game_date)} – {formatDate(player.last_game_date)}
          {player.is_active ? ' · Active' : ''}
        </p>
        <dl className="facts">
          {facts.map(([label, value]) => (
            <div key={label}>
              <dt>{label}</dt>
              <dd>{value}</dd>
            </div>
          ))}
        </dl>
        {bioLoading && <p className="muted small">Loading bio details…</p>}
        {bioError && <p className="muted small">Bio details are unavailable right now.</p>}
      </div>

      {bio?.jersey && (
        <div className="jersey" aria-label={`Jersey number ${bio.jersey}`}>
          #{bio.jersey}
        </div>
      )}

      <div className="elo-score">
        <span className="elo-score__label">Elo</span>
        <span className="elo-score__value">{formatRating(player.rating)}</span>
        <span className="elo-score__detail">
          {player.active_rank != null ? `#${player.active_rank} among active players` : 'Final rating'}
        </span>
        <span className="elo-score__detail">
          Peak {formatRating(player.peak_rating)} (#{player.peak_rank} all-time) ·{' '}
          {formatDate(player.peak_date)}
        </span>
      </div>
    </section>
  )
}
