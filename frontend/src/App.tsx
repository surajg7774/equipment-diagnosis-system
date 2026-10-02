import { Navigate, Route, Routes } from 'react-router-dom'
import { Layout } from './components/Layout'
import { DiagnosePage } from './pages/DiagnosePage'
import { HistoryPage } from './pages/HistoryPage'
import { StatsPage } from './pages/StatsPage'

export default function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<DiagnosePage />} />
        <Route path="history" element={<HistoryPage />} />
        <Route path="stats" element={<StatsPage />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  )
}
