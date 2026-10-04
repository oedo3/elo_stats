import { QueryClientProvider } from '@tanstack/react-query'
import { lazy, Suspense, useState } from 'react'
import { Link, Route, Routes } from 'react-router'
import { createQueryClient } from './api/queryClient'
import { Layout } from './components/Layout'
import { AboutPage } from './pages/AboutPage'
import { HomePage } from './pages/HomePage'
import { StatusMessage } from './components/StatusMessage'

// The player page carries the charting library; load it only when needed.
const PlayerPage = lazy(() => import('./pages/PlayerPage').then((m) => ({ default: m.PlayerPage })))

function NotFound() {
  return (
    <div className="card">
      <h1>Page not found</h1>
      <p>
        <Link to="/">Back to the leaderboard</Link>
      </p>
    </div>
  )
}

export function AppRoutes() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<HomePage />} />
        <Route
          path="players/:playerId"
          element={
            <Suspense fallback={<StatusMessage kind="loading" message="Loading player…" />}>
              <PlayerPage />
            </Suspense>
          }
        />
        <Route path="about" element={<AboutPage />} />
        <Route path="*" element={<NotFound />} />
      </Route>
    </Routes>
  )
}

export default function App() {
  const [queryClient] = useState(createQueryClient)
  return (
    <QueryClientProvider client={queryClient}>
      <AppRoutes />
    </QueryClientProvider>
  )
}
