'use client'

import { createContext, useContext, useState, useEffect, ReactNode } from 'react'
import { useRouter } from 'next/navigation'
import { authAPI, type MeResponse } from '@/lib/api'

interface AuthContextType {
  user: MeResponse | null
  isAuthenticated: boolean
  isLoading: boolean
  login: (username: string, password: string, totp_code?: string) => Promise<{ totp_required: boolean }>
  logout: () => void
}

const AuthContext = createContext<AuthContextType | undefined>(undefined)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<MeResponse | null>(null)
  const [isAuthenticated, setIsAuthenticated] = useState(false)
  const [isLoading, setIsLoading] = useState(true)
  const router = useRouter()

  const clearSession = () => {
    localStorage.removeItem('access_token')
    localStorage.removeItem('refresh_token')
    setUser(null)
    setIsAuthenticated(false)
  }

  useEffect(() => {
    let cancelled = false
    const clearSessionIfMounted = () => {
      localStorage.removeItem('access_token')
      localStorage.removeItem('refresh_token')
      if (!cancelled) {
        setUser(null)
        setIsAuthenticated(false)
      }
    }

    const token = localStorage.getItem('access_token')
    if (token) {
      authAPI.me().then(u => {
        if (!cancelled) {
          setUser(u)
          setIsAuthenticated(true)
        }
      }).catch(() => {
        clearSessionIfMounted()
      }).finally(() => {
        if (!cancelled) setIsLoading(false)
      })
    } else {
      setIsLoading(false)
    }

    return () => {
      cancelled = true
    }
  }, [])

  const login = async (username: string, password: string, totp_code?: string) => {
    const data = await authAPI.login(username, password, totp_code)
    if (data.totp_required) {
      return { totp_required: true }
    }
    try {
      const me = await authAPI.me(data.access_token)
      localStorage.setItem('access_token', data.access_token)
      localStorage.setItem('refresh_token', data.refresh_token)
      setUser(me)
      setIsAuthenticated(true)
      router.push('/')
      return { totp_required: false }
    } catch (error) {
      clearSession()
      throw error
    }
  }

  const logout = () => {
    clearSession()
    router.push('/login')
  }

  return (
    <AuthContext.Provider value={{ user, isAuthenticated, isLoading, login, logout }}>
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth() {
  const context = useContext(AuthContext)
  if (!context) throw new Error('useAuth must be used within AuthProvider')
  return context
}
