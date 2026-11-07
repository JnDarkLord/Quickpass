import { describe, it, expect, beforeEach, afterEach, vi } from "vitest"
import { render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { App } from "@/App"
import { supabase, getPortalBackend, setPortalBackend, resetPortalBackend } from "@/lib/supabase"
import type { UserProfile } from "@/context/AuthContext"
import { emptyYearView, mockBackend, spanishSchool, stubSupabaseHttp } from "./support"

const teacherProfile: UserProfile = {
  id: 20,
  email: "laura.solis@school.edu",
  role: "teacher",
  name: "Prof. Laura Solis",
  linked_entity_id: "20",
  details: { taught_grade: 5, badge_uid: "RLS_T_G5" },
}

describe("All Sections travels as a neutral value", () => {
  beforeEach(() => {
    localStorage.clear()
    resetPortalBackend()
    vi.spyOn(supabase.auth, "getSession").mockResolvedValue({ data: { session: null }, error: null } as never)
  })

  afterEach(() => {
    vi.restoreAllMocks()
    vi.unstubAllGlobals()
    resetPortalBackend()
  })

  it("sends no Section filter for the Day View or the Year View when the Teacher chooses every Section", async () => {
    const user = userEvent.setup()
    window.history.pushState({}, "", "/teacher")
    const fetchDayView = vi.fn().mockResolvedValue({
      date: "2026-10-16",
      grade: 5,
      summary: { total_enrolled: 0, present_today: 0, late_today: 0, absent_today: 0, attendance_rate: 100 },
      students: [],
    })
    const fetchYearView = vi.fn().mockResolvedValue({ ...emptyYearView, grade: 5 })
    setPortalBackend(
      mockBackend({ getCurrentSessionProfile: vi.fn().mockResolvedValue(teacherProfile), fetchDayView, fetchYearView })
    )

    render(<App />)
    await user.click(await screen.findByRole("button", { name: /^B$/ }))
    await waitFor(() => expect(fetchDayView).toHaveBeenLastCalledWith(expect.objectContaining({ section: "B" })))

    await user.click(screen.getByRole("button", { name: /^Todas$/ }))
    await waitFor(() => expect(fetchDayView).toHaveBeenLastCalledWith(expect.objectContaining({ section: undefined })))

    await user.click(screen.getByRole("button", { name: /Historial \(Año\)/i }))
    await waitFor(() => expect(fetchYearView).toHaveBeenLastCalledWith(expect.objectContaining({ section: undefined })))
  })

  it("passes TODAS to the Year View function as an ordinary Section name", async () => {
    const requests = stubSupabaseHttp(() => ({ status: 200, body: emptyYearView }))

    await getPortalBackend().fetchYearView({ grade: 5, section: "TODAS" })
    await getPortalBackend().fetchYearView({ grade: 5 })

    const rpcBodies = requests
      .filter((r) => r.url.pathname.endsWith("/rpc/get_year_view_stats"))
      .map((r) => r.body as Record<string, unknown>)
    expect(rpcBodies.map((b) => b.p_section)).toEqual(["TODAS", null])
  })

  it("filters the Day View roster by a Section named TODAS", async () => {
    stubSupabaseHttp((url) =>
      url.pathname.endsWith("/student_details")
        ? {
            status: 200,
            body: [
              { user_id: 1, grade: 5, section: "TODAS", family_id: "F1", users: { id: 1, full_name: "Ana", badge_uid: "A1", role: "student", is_active: true } },
              { user_id: 2, grade: 5, section: "B", family_id: "F2", users: { id: 2, full_name: "Leo", badge_uid: "B2", role: "student", is_active: true } },
            ],
          }
        : { status: 200, body: [] }
    )

    const named = await getPortalBackend().fetchDayView({ date: "2026-10-16", grade: 5, section: "TODAS" })
    const every = await getPortalBackend().fetchDayView({ date: "2026-10-16", grade: 5 })

    expect(named.students.map((s) => s.name)).toEqual(["Ana"])
    expect(every.students.map((s) => s.name).sort()).toEqual(["Ana", "Leo"])
  })
})

describe("Unregistered email is recognized by its error code", () => {
  beforeEach(() => {
    localStorage.clear()
    window.history.pushState({}, "", "/login")
    resetPortalBackend()
    vi.spyOn(supabase.auth, "getSession").mockResolvedValue({ data: { session: null }, error: null } as never)
  })

  afterEach(() => {
    vi.restoreAllMocks()
    vi.unstubAllGlobals()
    resetPortalBackend()
  })

  it("shows the unregistered-email message when the Web Account lookup rejects with the code, whatever its text says", async () => {
    const user = userEvent.setup()
    vi.spyOn(supabase.auth, "signUp").mockResolvedValue({
      data: { user: { id: "new-user" }, session: { access_token: "token" } },
      error: null,
    } as never)
    stubSupabaseHttp((url) => {
      if (url.pathname.endsWith("/rpc/get_school_settings")) {
        return { status: 200, body: spanishSchool }
      }
      return url.pathname.endsWith("/rpc/get_web_account")
        ? {
            status: 400,
            body: { code: "P0001", message: "ERR_UNAUTHORIZED_EMAIL", details: "Wording that may change", hint: null },
          }
        : { status: 200, body: [] }
    })

    render(<App />)
    await user.click(await screen.findByRole("button", { name: /¿Primera vez\? Activar/i }))
    await user.type(screen.getByLabelText(/Correo Autorizado/i), "intruder@outsider.org")
    await user.type(screen.getByLabelText(/Nueva Contraseña/i), "Secret123!")
    await user.type(screen.getByLabelText(/Confirmar Contraseña/i), "Secret123!")
    await user.click(screen.getByRole("button", { name: /Crear Contraseña e Ingresar/i }))

    expect(
      await screen.findByText(/Este correo no está registrado en el sistema escolar\. Comuníquese con la administración\./i)
    ).toBeInTheDocument()
    expect(screen.queryByText(/Wording that may change/)).not.toBeInTheDocument()
  })
})
