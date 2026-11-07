import React, { createContext, useContext, useEffect, useState } from "react"
import { getPortalBackend } from "@/lib/supabase"

export interface UserProfile {
  id: number
  email: string
  role: "guardian" | "teacher" | "admin"
  name: string
  linked_entity_id: string
  details: Record<string, any>
}

export type WebAccount = UserProfile

interface AuthContextType {
  user: UserProfile | null
  isLoading: boolean
  login: (email: string, password: string) => Promise<UserProfile>
  registerFirstTime: (email: string, password: string) => Promise<UserProfile>
  loginWithGoogle: () => Promise<UserProfile | null>
  logout: () => Promise<void>
}

const AuthContext = createContext<AuthContextType | null>(null)

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<UserProfile | null>(() => {
    const saved = localStorage.getItem("quickpass_user")
    return saved ? JSON.parse(saved) : null
  })
  const [isLoading, setIsLoading] = useState(true)

  const syncWebAccountState = (account: UserProfile | null) => {
    setUser(account)
    if (account) {
      localStorage.setItem("quickpass_user", JSON.stringify(account))
    } else {
      localStorage.removeItem("quickpass_user")
    }
  }

  useEffect(() => {
    let isMounted = true
    const backend = getPortalBackend()

    async function verifySession() {
      try {
        const account = await backend.getCurrentSessionProfile()
        if (!isMounted) return
        syncWebAccountState(account)
      } catch {
        if (!isMounted) return
        syncWebAccountState(null)
      } finally {
        if (isMounted) {
          setIsLoading(false)
        }
      }
    }

    verifySession()

    const unsubscribe = backend.onAuthStateChange((account) => {
      if (!isMounted) return
      syncWebAccountState(account)
    })

    return () => {
      isMounted = false
      unsubscribe()
    }
  }, [])

  const login = async (email: string, password: string) => {
    const account = await getPortalBackend().signInWithPassword(email, password)
    syncWebAccountState(account)
    return account
  }

  const registerFirstTime = async (email: string, password: string) => {
    const account = await getPortalBackend().signUpFirstTime(email, password)
    syncWebAccountState(account)
    return account
  }

  const loginWithGoogle = async () => {
    const account = await getPortalBackend().signInWithGoogle()
    if (account) {
      syncWebAccountState(account)
      return account
    }
    return null
  }

  const logout = async () => {
    await getPortalBackend().signOut()
    syncWebAccountState(null)
  }

  return (
    <AuthContext.Provider
      value={{
        user,
        isLoading,
        login,
        registerFirstTime,
        loginWithGoogle,
        logout,
      }}
    >
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth() {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error("useAuth must be used within an AuthProvider")
  return ctx
}
