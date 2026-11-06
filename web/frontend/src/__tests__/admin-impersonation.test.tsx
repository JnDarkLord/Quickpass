import { describe, it, expect, beforeEach, vi } from "vitest"
import { render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { App } from "@/App"
import { setPortalBackend, resetPortalBackend } from "@/lib/supabase"
import type { UserProfile } from "@/context/AuthContext"
import { mockBackend } from "./support"

const adminProfile: UserProfile = {
  id: 57,
  email: "admin@school.edu",
  role: "admin",
  name: "Carlos Mendoza",
  linked_entity_id: "ADMIN-0001",
  details: { badge_uid: "ADMIN-0001" },
}

describe("Admin Multi-Role Impersonation and View Switcher", () => {
  beforeEach(() => {
    localStorage.clear()
    resetPortalBackend()
    vi.clearAllMocks()
  })

  it("allows admin to access /teacher, change grade to simulate any teacher view", async () => {
    const user = userEvent.setup()
    window.history.pushState({}, "", "/teacher")

    const fetchDayViewMock = vi.fn().mockResolvedValue({
      date: "2026-10-19",
      grade: 1,
      summary: { total_enrolled: 1, present_today: 1, late_today: 0, absent_today: 0, attendance_rate: 100 },
      students: [
        {
          student_id: 201,
          name: "Albano Llopis",
          badge_uid: "UID-ALB",
          grade: 1,
          section: "A",
          family_id: "FAM-0001",
          check_in_time: "06:45:00",
          check_out_time: null,
          status: "on_time",
          punctuality: "on_time",
          departed: false,
        },
      ],
    })

    const backend = mockBackend({
      getCurrentSessionProfile: vi.fn().mockResolvedValue(adminProfile),
      fetchDayView: fetchDayViewMock,
      fetchYearView: vi.fn().mockResolvedValue({
        grade: 1,
        total_students: 1,
        summary: { total_students: 1, total_present_days: 1, total_late_days: 0, total_absent_days: 0, average_punctuality: 100 },
        students: [],
      }),
    })
    setPortalBackend(backend)

    render(<App />)

    // Admin bar should be rendered
    await waitFor(() => {
      expect(screen.getByText("Modo Administrador:")).toBeInTheDocument()
      expect(screen.getByText("Ver como Docente")).toBeInTheDocument()
    })

    // Simulated grade badge
    expect(screen.getByText("Simulando 1°")).toBeInTheDocument()

    // Select grade 5
    const gradeSelect = screen.getByLabelText(/Seleccionar grado/i)
    await user.selectOptions(gradeSelect, "5")

    await waitFor(() => {
      expect(fetchDayViewMock).toHaveBeenCalledWith(expect.objectContaining({ grade: 5 }))
    })
  })

  it("allows admin to access /guardian, view family information and switcher", async () => {
    window.history.pushState({}, "", "/guardian")

    const fetchDayViewMock = vi.fn().mockResolvedValue({
      date: "2026-10-19",
      family_id: "FAM-0001",
      summary: { total_enrolled: 1, present_today: 1, late_today: 0, absent_today: 0, attendance_rate: 100 },
      students: [
        {
          student_id: 101,
          name: "Albano Llopis",
          badge_uid: "UID-ALB",
          grade: 1,
          section: "A",
          family_id: "FAM-0001",
          check_in_time: "06:45:00",
          check_out_time: null,
          status: "on_time",
          punctuality: "on_time",
          departed: false,
        },
      ],
    })

    const backend = mockBackend({
      getCurrentSessionProfile: vi.fn().mockResolvedValue(adminProfile),
      fetchDayView: fetchDayViewMock,
      fetchYearView: vi.fn().mockResolvedValue({
        family_id: "FAM-0001",
        total_students: 1,
        summary: { total_students: 1, total_present_days: 1, total_late_days: 0, total_absent_days: 0, average_punctuality: 100 },
        students: [
          {
            student_id: 101,
            name: "Albano Llopis",
            grade: 1,
            section: "A",
            family_id: "FAM-0001",
            present_days: 1,
            late_days: 0,
            absent_days: 0,
            punctuality_rate: 100,
            metrics: { present_days: 1, late_days: 0, absent_days: 0, punctuality_rate: 100 },
            days: {},
            history: [],
          },
        ],
      }),
    })
    setPortalBackend(backend)

    render(<App />)

    const user = userEvent.setup()

    await waitFor(() => {
      expect(screen.getByText(/Familia FAM-0001/i)).toBeInTheDocument()
      expect(screen.getByText("Simulación Admin")).toBeInTheDocument()
      expect(screen.getByText("Albano Llopis")).toBeInTheDocument()
    })

    // Test typing a family code (e.g. 9999) directly in the input
    const familyInput = screen.getByLabelText(/Código de familia/i)
    await user.clear(familyInput)
    await user.type(familyInput, "9999")
    await user.click(screen.getByRole("button", { name: /Buscar/i }))

    await waitFor(() => {
      expect(fetchDayViewMock).toHaveBeenCalledWith(
        expect.objectContaining({ familyId: "FAM-9999" })
      )
    })
  })
})
