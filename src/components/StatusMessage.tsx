import { errorMessage } from '../lib/errors'

type Kind = 'loading' | 'error' | 'empty'

interface StatusMessageProps {
  kind: Kind
  message?: string
  error?: unknown
  onRetry?: () => void
}

const DEFAULTS: Record<Kind, string> = {
  loading: 'Loading…',
  error: 'Something went wrong.',
  empty: 'Nothing to show yet.',
}

export function StatusMessage({ kind, message, error, onRetry }: StatusMessageProps) {
  const text = message ?? (kind === 'error' ? errorMessage(error) : DEFAULTS[kind])
  return (
    <div
      className={`status status--${kind}`}
      role={kind === 'error' ? 'alert' : 'status'}
      aria-live="polite"
    >
      {kind === 'loading' && <span className="spinner" aria-hidden="true" />}
      <span>{text}</span>
      {onRetry && (
        <button type="button" className="button button--ghost" onClick={onRetry}>
          Try again
        </button>
      )}
    </div>
  )
}
