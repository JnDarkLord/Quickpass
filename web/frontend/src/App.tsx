import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom"
import { AuthProvider, useAuth } from "@/context/AuthContext"
import { SchoolProvider } from "@/context/SchoolContext"
import { ProtectedRoute } from "@/components/ProtectedRoute"
import { LoginPage } from "@/pages/Login"
import { GuardianPortal } from "@/pages/GuardianPortal"
import { TeacherPortal } from "@/pages/TeacherPortal"
import { AdminPortal } from "@/pages/AdminPortal"

function RootRedirect() {
  const { user, isLoading } = useAuth()

  if (isLoading) {
    return (
      <div className="flex h-screen w-screen items-center justify-center bg-slate-50">
        <div className="h-8 w-8 animate-spin rounded-full border-4 border-blue-600 border-t-transparent" />
      </div>
    )
  }

  if (!user) {
    return <Navigate to="/login" replace />
  }

  return <Navigate to={`/${user.role}`} replace />
}

export function App() {
  return (
    <AuthProvider>
      <SchoolProvider>
        <BrowserRouter>
          <Routes>
            <Route path="/login" element={<LoginPage />} />
            <Route
              path="/guardian"
              element={
                <ProtectedRoute allowedRole="guardian">
                  <GuardianPortal />
                </ProtectedRoute>
              }
            />
            <Route
              path="/teacher"
              element={
                <ProtectedRoute allowedRole="teacher">
                  <TeacherPortal />
                </ProtectedRoute>
              }
            />
            <Route
              path="/admin"
              element={
                <ProtectedRoute allowedRole="admin">
                  <AdminPortal />
                </ProtectedRoute>
              }
            />
            <Route path="/" element={<RootRedirect />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </BrowserRouter>
      </SchoolProvider>
    </AuthProvider>
  )
}

export default App
