import { useParams } from 'react-router'
import { useEloHistory, usePlayer, usePlayerBio, usePlayerCareer } from '../api/hooks'
import { EloChart } from '../components/EloChart'
import { PlayerProfile } from '../components/PlayerProfile'
import { StatsTable } from '../components/StatsTable'
import { StatusMessage } from '../components/StatusMessage'
import { parsePlayerId } from '../lib/playerId'

export function PlayerPage() {
  const playerId = parsePlayerId(useParams().playerId)
  if (playerId === null) return <StatusMessage kind="error" message="That isn't a valid player link." />
  return <PlayerDetail key={playerId} playerId={playerId} />
}

function PlayerDetail({ playerId }: { playerId: number }) {
  const player = usePlayer(playerId)
  const elo = useEloHistory(playerId)
  const bio = usePlayerBio(playerId)
  const career = usePlayerCareer(playerId)

  if (player.isPending) return <StatusMessage kind="loading" message="Loading player…" />
  if (player.isError) {
    return <StatusMessage kind="error" error={player.error} onRetry={() => player.refetch()} />
  }

  return (
    <div className="stack">
      <PlayerProfile
        player={player.data}
        bio={bio.data}
        bioLoading={bio.isPending}
        bioError={bio.isError}
      />

      {elo.isPending && <StatusMessage kind="loading" message="Loading Elo history…" />}
      {elo.isError && <StatusMessage kind="error" error={elo.error} onRetry={() => elo.refetch()} />}
      {elo.data && <EloChart history={elo.data} />}

      {career.isPending && <StatusMessage kind="loading" message="Loading career stats…" />}
      {career.isError && (
        <StatusMessage kind="error" error={career.error} onRetry={() => career.refetch()} />
      )}
      {career.data && <StatsTable career={career.data} />}
    </div>
  )
}
