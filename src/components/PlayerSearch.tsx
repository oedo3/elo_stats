import { useQueryClient } from '@tanstack/react-query'
import { useId, useRef, useState, type FormEvent, type KeyboardEvent } from 'react'
import { useNavigate } from 'react-router'
import { searchQuery, usePlayerSearch } from '../api/hooks'
import { useDebouncedValue } from '../hooks/useDebouncedValue'
import { formatRating } from '../lib/format'

const MIN_QUERY = 2

export function PlayerSearch() {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const inputRef = useRef<HTMLInputElement>(null)
  const listboxId = useId()
  const [text, setText] = useState('')
  const [open, setOpen] = useState(false)
  const [active, setActive] = useState(-1)
  const query = useDebouncedValue(text.trim(), 200)
  const { data, isFetching, isError, error, isPlaceholderData } = usePlayerSearch(query)
  // Results only count once they belong to exactly what is typed (not a debounced/older query).
  const isCurrent = query.length >= MIN_QUERY && text.trim() === query && !isPlaceholderData
  const results = query.length >= MIN_QUERY ? (data ?? []) : []

  const showList = open && query.length >= MIN_QUERY

  const goTo = (playerId: number) => {
    setOpen(false)
    setActive(-1)
    setText('')
    navigate(`/players/${playerId}`)
  }

  const onSubmit = async (event: FormEvent) => {
    event.preventDefault()
    if (isCurrent) {
      const choice = results[active] ?? results[0]
      if (choice) goTo(choice.player_id)
      return
    }
    // Enter pressed before the debounced results caught up: search the exact text now.
    const typed = text.trim()
    if (typed.length < MIN_QUERY) return
    try {
      const fresh = await queryClient.fetchQuery(searchQuery(typed))
      const first = fresh[0]
      if (first && inputRef.current?.value.trim() === typed) goTo(first.player_id)
    } catch {
      // The dropdown shows the error from the debounced query.
    }
  }

  const onKeyDown = (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key === 'ArrowDown') {
      event.preventDefault()
      setOpen(true)
      setActive((i) => Math.min(i + 1, results.length - 1))
    } else if (event.key === 'ArrowUp') {
      event.preventDefault()
      setActive((i) => Math.max(i - 1, -1))
    } else if (event.key === 'Escape') {
      setOpen(false)
      setActive(-1)
    }
  }

  return (
    <form className="search" role="search" onSubmit={onSubmit}>
      <label htmlFor={`${listboxId}-input`} className="visually-hidden">
        Search for a player
      </label>
      <input
        id={`${listboxId}-input`}
        ref={inputRef}
        type="search"
        placeholder="Search for a player"
        autoComplete="off"
        value={text}
        maxLength={60}
        role="combobox"
        aria-expanded={showList}
        aria-controls={listboxId}
        aria-autocomplete="list"
        aria-activedescendant={active >= 0 ? `${listboxId}-${active}` : undefined}
        onChange={(event) => {
          setText(event.target.value)
          setOpen(true)
          setActive(-1)
        }}
        onFocus={() => setOpen(true)}
        onBlur={() => window.setTimeout(() => setOpen(false), 150)}
        onKeyDown={onKeyDown}
      />
      <button type="submit" className="button" aria-label="Search">
        <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true">
          <circle cx="11" cy="11" r="7" fill="none" stroke="currentColor" strokeWidth="2" />
          <path d="m20 20-3.5-3.5" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
        </svg>
      </button>

      {showList && (
        <ul
          id={listboxId}
          role="listbox"
          className={`search__results${isCurrent ? '' : ' is-stale'}`}
          aria-busy={!isCurrent}
        >
          {isError && <li className="search__note">{(error as Error).message}</li>}
          {!isError && results.length === 0 && (
            <li className="search__note">{isFetching ? 'Searching…' : 'No players found'}</li>
          )}
          {results.map((player, index) => (
            <li
              key={player.player_id}
              id={`${listboxId}-${index}`}
              role="option"
              aria-selected={index === active}
              className="search__option"
              onMouseDown={(event) => event.preventDefault()}
              onClick={() => goTo(player.player_id)}
            >
              <span className="search__name">{player.player_name}</span>
              <span className="search__detail">
                {player.team_abbr} · {player.first_game_date.slice(0, 4)}–
                {player.last_game_date.slice(0, 4)}
              </span>
              <span className="search__elo">{formatRating(player.rating)}</span>
            </li>
          ))}
        </ul>
      )}
    </form>
  )
}
