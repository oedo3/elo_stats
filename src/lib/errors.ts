const FALLBACK = 'Something went wrong.'

export function errorMessage(error: unknown, fallback = FALLBACK): string {
  return error instanceof Error && error.message ? error.message : fallback
}
