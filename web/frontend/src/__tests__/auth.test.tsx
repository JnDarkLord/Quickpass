import { describe, it, expect, beforeEach, vi } from "vitest"
import { render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { App } from "@/App"
import { ERR_UNAUTHORIZED_EMAIL, setPortalBackend, resetPortalBackend } from "@/lib/supabase"
import type { UserProfile } from "@/context/AuthContext"
import { mockBackend as createMockBackend } from "./support"

describe("Web Account Authentication & Authorized Email Enforcement", () => {
  beforeEach(() => {
    localStorage.clear()
    window.history.pushState({}, "", "/login")
    resetPortalBackend()
  })

  it("displays explanatory Spanish error banner when an unauthorized email attempts first-time registration", async () => {
    const user = userEvent.setup()
    const mockBackend = createMockBackend({
      signUpFirstTime: vi.fn().mockRejectedValue(new Error(ERR_UNAUTHORIZED_EMAIL)),
    })
    setPortalBackend(mockBackend)

    render(<App />)
    await waitFor(() => expect(screen.getByText("Iniciar Sesión")).toBeInTheDocument())

    await user.click(screen.getByRole("button", { name: /¿Primera vez\? Activar/i }))
    await user.type(screen.getByLabelText(/Correo Autorizado/i), "intruder@outsider.org")
    await user.type(screen.getByLabelText(/Nueva Contraseña/i), "Secret123!")
    await user.type(screen.getByLabelText(/Confirmar Contraseña/i), "Secret123!")
    await user.click(screen.getByRole("button", { name: /Crear Contraseña e Ingresar/i }))

    await waitFor(() => {
      expect(
        screen.getByText(/Este correo no está registrado en el sistema escolar\. Comuníquese con la administración\./i)
      ).toBeInTheDocument()
    })
  })

  it("routes a pre-registered Guardian to the Guardian portal with their Family Code upon password sign-in", async () => {
    const user = userEvent.setup()
    const guardianProfile: UserProfile = {
      id: 10,
      email: "elena.mendoza@school.edu",
      role: "guardian",
      name: "Elena Mendoza",
      linked_entity_id: "FAM-5001",
      details: { family_id: "FAM-5001", children: [] },
    }
    const mockBackend = createMockBackend({
      signInWithPassword: vi.fn().mockResolvedValue(guardianProfile),
    })
    setPortalBackend(mockBackend)

    render(<App />)
    await waitFor(() => expect(screen.getByLabelText(/Correo Electrónico Registrado/i)).toBeInTheDocument())

    await user.type(screen.getByLabelText(/Correo Electrónico Registrado/i), "elena.mendoza@school.edu")
    await user.type(screen.getByLabelText(/^Contraseña$/i), "Password123!")
    await user.click(screen.getByRole("button", { name: /Ingresar con Correo/i }))

    await waitFor(() => {
      expect(screen.getByText(/Familia Elena Mendoza/i)).toBeInTheDocument()
      expect(screen.getAllByText(/FAM-5001/i).length).toBeGreaterThan(0)
    })
  })

  it("persists an active Supabase session across reloads and clears session on sign-out", async () => {
    const user = userEvent.setup()
    const teacherProfile: UserProfile = {
      id: 20,
      email: "laura.solis@school.edu",
      role: "teacher",
      name: "Prof. Laura Solis",
      linked_entity_id: "20",
      details: { taught_grade: 5, badge_uid: "RLS_T_G5" },
    }
    const signOutMock = vi.fn().mockResolvedValue(undefined)
    const mockBackend = createMockBackend({
      getCurrentSessionProfile: vi.fn().mockResolvedValue(teacherProfile),
      signOut: signOutMock,
    })
    setPortalBackend(mockBackend)
    window.history.pushState({}, "", "/")

    render(<App />)

    await waitFor(() => {
      expect(screen.getAllByText(/Prof\. Laura Solis/i).length).toBeGreaterThan(0)
      expect(screen.getByText("Grado Asignado: 5°")).toBeInTheDocument()
    })

    // Sign out
    const logoutBtn = screen.getByTitle("Cerrar sesión")
    await user.click(logoutBtn)

    await waitFor(() => {
      expect(signOutMock).toHaveBeenCalled()
      expect(screen.getByText("Iniciar Sesión")).toBeInTheDocument()
    })
  })
})
