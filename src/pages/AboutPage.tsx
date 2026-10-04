import { useMeta } from '../api/hooks'

export function AboutPage() {
  const params = useMeta().data?.elo_params

  return (
    <article className="card prose">
      <h1>How the Elo works</h1>
      <p>
        Every NBA player starts at <strong>1500</strong>. After every regular-season and playoff game
        since 1996-97, each player who logged minutes gets a new rating:
      </p>
      <ol>
        <li>
          Each team's strength is the <strong>minutes-weighted average</strong> of its players'
          ratings going into the game.
        </li>
        <li>
          The home team gets a <strong>{params?.home_advantage ?? 100}-point</strong> bonus when
          working out who was expected to win.
        </li>
        <li>
          The team's rating swing is <code>K × margin multiplier × (result − expected)</code>, with
          K = {params?.k_factor ?? 20}. Bigger wins count for more, but blowouts by heavy favourites
          are damped (the FiveThirtyEight margin-of-victory formula).
        </li>
        <li>
          Each player gets that swing scaled by the <strong>share of the game they played</strong>,
          so a 40-minute starter moves far more than a 5-minute reserve.
        </li>
        <li>
          At the start of each new season, ratings move{' '}
          {Math.round((params?.season_reversion ?? 0.25) * 100)}% of the way back to 1500.
        </li>
      </ol>
      <p>
        Because a rating only moves with wins and losses, it measures how much a player's minutes go
        with winning against the opponents they faced. It doesn't measure box-score production. A
        great player on a losing team can still have a modest Elo.
      </p>
    </article>
  )
}
