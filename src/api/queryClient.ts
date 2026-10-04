import { QueryClient } from '@tanstack/react-query'
import { shouldRetry } from './hooks'

export function createQueryClient() {
  return new QueryClient({
    defaultOptions: {
      queries: { retry: shouldRetry, refetchOnWindowFocus: false, staleTime: 60_000 },
    },
  })
}
