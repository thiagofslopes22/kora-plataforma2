import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { AuthProvider, useAuth } from './contexts/AuthContext'
import AppShell from './components/AppShell'
import { Spinner } from './ui'

import LoginPage from './pages/LoginPage'
import HomePage from './pages/HomePage'
import ConciliacaoRgfPage from './pages/ConciliacaoRgfPage'
import ConciliacaoRreoPage from './pages/ConciliacaoRreoPage'
import AuditoriaPage from './pages/AuditoriaPage'
import MunicipiosPage from './pages/MunicipiosPage'
import MunicipioDetailPage from './pages/MunicipioDetailPage'
import UsuariosPage from './pages/UsuariosPage'

function FullLoader() {
  return (
    <div className="flex min-h-[100dvh] items-center justify-center text-gold">
      <Spinner size={26} />
    </div>
  )
}

function Protected({ children, adminOnly = false }) {
  const { user, loading, isAdmin } = useAuth()
  if (loading) return <FullLoader />
  if (!user) return <Navigate to="/login" replace />
  if (adminOnly && !isAdmin) return <Navigate to="/" replace />
  return <AppShell>{children}</AppShell>
}

function AppRoutes() {
  const { user, loading } = useAuth()
  return (
    <Routes>
      <Route
        path="/login"
        element={loading ? <FullLoader /> : user ? <Navigate to="/" replace /> : <LoginPage />}
      />
      <Route path="/" element={<Protected><HomePage /></Protected>} />
      <Route path="/conciliacao/rgf" element={<Protected><ConciliacaoRgfPage /></Protected>} />
      <Route path="/conciliacao/rreo" element={<Protected><ConciliacaoRreoPage /></Protected>} />
      <Route path="/auditoria" element={<Protected><AuditoriaPage /></Protected>} />
      <Route path="/municipios" element={<Protected><MunicipiosPage /></Protected>} />
      <Route path="/municipios/:id" element={<Protected><MunicipioDetailPage /></Protected>} />
      <Route path="/usuarios" element={<Protected adminOnly><UsuariosPage /></Protected>} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}

export default function App() {
  return (
    <AuthProvider>
      <BrowserRouter>
        <AppRoutes />
      </BrowserRouter>
    </AuthProvider>
  )
}
