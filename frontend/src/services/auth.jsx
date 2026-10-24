import { createContext, useContext, useEffect, useState } from 'react'
import api, { TOKEN_KEY } from './api'

const AuthContext = createContext(null)

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null)
  const [loading, setLoading] = useState(() => !!localStorage.getItem(TOKEN_KEY))

  // Restore session from a saved token
  useEffect(() => {
    if (!localStorage.getItem(TOKEN_KEY)) return
    api.get('/auth/me')
      .then((res) => setUser(res.data))
      .catch(() => localStorage.removeItem(TOKEN_KEY))
      .finally(() => setLoading(false))
  }, [])

  const saveSession = (data) => {
    localStorage.setItem(TOKEN_KEY, data.access_token)
    setUser(data.user)
  }

  const login = async (email, password) => {
    const res = await api.post('/auth/login', { email, password })
    saveSession(res.data)
  }

  const register = async (email, password, role) => {
    const res = await api.post('/auth/register', { email, password, role })
    saveSession(res.data)
  }

  const logout = () => {
    localStorage.removeItem(TOKEN_KEY)
    setUser(null)
  }

  return (
    <AuthContext.Provider value={{ user, loading, login, register, logout }}>
      {children}
    </AuthContext.Provider>
  )
}

export const useAuth = () => useContext(AuthContext)
