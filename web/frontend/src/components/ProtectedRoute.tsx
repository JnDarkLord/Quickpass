import React from "react"
import { Navigate } from "react-router-dom"
import { useAuth } from "@/context/AuthContext"
import { useSchool } from "@/context/SchoolContext"

interface ProtectedRouteProps {
  children: React.ReactNode
  allowedRole?: "guardian" | "teacher" | "admin"
}

export function ProtectedRoute({ children, allowedRole }: ProtectedRouteProps) {
  const { user, isLoading } = useAuth()
  const { t } = useSchool()

  if (isLoading) {
    return (
      <div className="flex h-screen w-screen items-center justify-center bg-slate-50">
        <div className="flex flex-col items-center space-y-3">
          <div className="h-8 w-8 animate-spin rounded-full border-4 border-blue-600 border-t-transparent" />
          <p className="text-sm font-medium text-slate-500">{t("app.loading_session")}</p>
        </div>
      </div>
    )
  }

  if (!user) {
    return <Navigate to="/login" replace />
  }

  if (allowedRole && user.role !== allowedRole) {
    if (user.role === "admin") {
      return <>{children}</>
    }
    // Redirect to their own dashboard
    return <Navigate to={`/${user.role}`} replace />
  }

  return <>{children}</>
}
