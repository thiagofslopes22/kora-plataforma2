import { createContext, useContext, useState, useEffect } from 'react'
import { api, getToken, setToken, clearToken } from '../lib/api'

const AuthContext = createContext(null)

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    const token = getToken()
    if (!token) {
      setLoading(false)
      return
    }
    api.get('/auth/me')
      .then((r) => (r.ok ? r.json() : null))
      .then((data) => {
        if (data) setUser(data)
        else clearToken()
      })
      .catch(() => clearToken())
      .finally(() => setLoading(false))
  }, [])

  function login(token, userData) {
    setToken(token)
    setUser(userData)
  }

  function logout() {
    clearToken()
    setUser(null)
  }

  const isAdmin = user?.role === 'admin'

  return (
    <AuthContext.Provider value={{ user, loading, isAdmin, login, logout }}>
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth() {
  return useContext(AuthContext)
}
