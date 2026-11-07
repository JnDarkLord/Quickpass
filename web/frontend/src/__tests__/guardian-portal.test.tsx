import { describe, it, expect, beforeEach, vi } from "vitest"
import { render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { App } from "@/App"
import { setPortalBackend, resetPortalBackend } from "@/lib/supabase"
import type { UserProfile } from "@/context/AuthContext"
import { mockBackend } from "./support"

const guardianProfile: UserProfile = {
  id: 1,
  email: "elena.mendoza@school.edu",
  role: "guardian",
  name: "Elena Mendoza",
  linked_entity_id: "FAM-5001",
  details: {
    family_id: "FAM-5001",
    children: [
      { id: 101, name: "Valeria Mendoza", badge_uid: "UID_VAL01", grade: 5, section: "A" },
      { id: 102, name: "Mateo Mendoza", badge_uid: "UID_MAT02", grade: 5, section: "B" },
    ],
  },
}

describe("Guardian Day View and Year View", () => {
  beforeEach(() => {
    localStorage.clear()
    window.history.pushState({}, "", "/guardian")
    resetPortalBackend()
  })

  it("renders Day View cards for all siblings in the Family Code and refreshes on click", async () => {
    const user = userEvent.setup()
    const fetchDayViewMock = vi.fn().mockResolvedValue({
      date: "2026-10-16",
      family_id: "FAM-5001",
      summary: {
        total_enrolled: 3,
        total_children: 3,
        present_today: 2,
        late_today: 1,
        absent_today: 1,
        attendance_rate: 66.7,
      },
      students: [
        {
          student_id: 101,
          name: "Valeria Mendoza",
          badge_uid: "UID_VAL01",
          grade: 5,
          section: "A",
          family_id: "FAM-5001",
          check_in_time: "06:42:00",
          check_out_time: "13:30:00",
          status: "departed",
          punctuality: "on_time",
          departed: true,
        },
        {
          student_id: 102,
          name: "Mateo Mendoza",
          badge_uid: "UID_MAT02",
          grade: 5,
          section: "B",
          family_id: "FAM-5001",
          check_in_time: "07:05:00",
          check_out_time: null,
          status: "late",
          punctuality: "late",
          departed: false,
        },
        {
          student_id: 103,
          name: "Lucas Mendoza",
          badge_uid: "UID_LUC03",
          grade: 2,
          section: "A",
          family_id: "FAM-5001",
          check_in_time: null,
          check_out_time: null,
          status: "absent",
          punctuality: "absent",
          departed: false,
        },
      ],
    })

    const backend = mockBackend({
      getCurrentSessionProfile: vi.fn().mockResolvedValue(guardianProfile),
      fetchDayView: fetchDayViewMock,
      fetchYearView: vi.fn().mockResolvedValue({
        family_id: "FAM-5001",
        total_students: 0,
        summary: { total_students: 0, total_present_days: 0, total_late_days: 0, total_absent_days: 0, average_punctuality: 100 },
        students: [],
      }),
    })
    setPortalBackend(backend)

    render(<App />)

    await waitFor(() => {
      expect(screen.getByText("Valeria Mendoza")).toBeInTheDocument()
      expect(screen.getByText("Mateo Mendoza")).toBeInTheDocument()
      expect(screen.getByText("Lucas Mendoza")).toBeInTheDocument()
    })

    // Status badges and times
    // The three cards' Check-out labels, and the badge of the child who checked out.
    expect(screen.getAllByText("Salida")).toHaveLength(4)
    expect(screen.getByText("06:42:00")).toBeInTheDocument()
    expect(screen.getByText("13:30:00")).toBeInTheDocument()
    expect(screen.getByText("Tarde")).toBeInTheDocument()
    expect(screen.getByText("En el Colegio")).toBeInTheDocument()
    expect(screen.getByText("Ausente")).toBeInTheDocument()

    // Manual refresh triggers fetchDayView again
    const callsBefore = fetchDayViewMock.mock.calls.length
    await user.click(screen.getByRole("button", { name: /Actualizar/i }))
    await waitFor(() => {
      expect(fetchDayViewMock.mock.calls.length).toBeGreaterThan(callsBefore)
    })
  })

  it("renders Year View KPIs, calendar indicators (P, T, A), history table, and toggles between siblings", async () => {
    const user = userEvent.setup()
    const now = new Date()
    const yr = now.getFullYear()
    const mStr = String(now.getMonth() + 1).padStart(2, "0")
    const d1 = `${yr}-${mStr}-05`
    const d2 = `${yr}-${mStr}-06`
    const d3 = `${yr}-${mStr}-07`

    const backend = mockBackend({
      getCurrentSessionProfile: vi.fn().mockResolvedValue(guardianProfile),
      fetchDayView: vi.fn().mockResolvedValue({
        date: d3,
        family_id: "FAM-5001",
        summary: { total_enrolled: 2, present_today: 2, late_today: 0, absent_today: 0, attendance_rate: 100 },
        students: [],
      }),
      fetchYearView: vi.fn().mockResolvedValue({
        family_id: "FAM-5001",
        total_students: 2,
        summary: {
          total_students: 2,
          total_present_days: 5,
          total_late_days: 2,
          total_absent_days: 1,
          average_punctuality: 58.4,
        },
        students: [
          {
            student_id: 101,
            name: "Valeria Mendoza",
            grade: 5,
            section: "A",
            present_days: 3,
            late_days: 1,
            absent_days: 0,
            punctuality_rate: 66.7,
            metrics: {
              present_days: 3,
              late_days: 1,
              absent_days: 0,
              punctuality_rate: 66.7,
            },
            days: { [d1]: "P", [d2]: "T", [d3]: "P" },
            history: [
              { date: d3, check_in_time: "06:35:00", check_out_time: "13:20:00", status: "departed" },
              { date: d2, check_in_time: "07:10:00", check_out_time: "13:25:00", status: "late" },
              { date: d1, check_in_time: "06:40:00", check_out_time: "13:30:00", status: "on_time" },
            ],
          },
          {
            student_id: 102,
            name: "Mateo Mendoza",
            grade: 5,
            section: "B",
            present_days: 2,
            late_days: 1,
            absent_days: 1,
            punctuality_rate: 50.0,
            metrics: {
              present_days: 2,
              late_days: 1,
              absent_days: 1,
              punctuality_rate: 50.0,
            },
            days: { [d1]: "T", [d2]: "P", [d3]: "A" },
            history: [
              { date: d3, check_in_time: null, check_out_time: null, status: "absent" },
              { date: d2, check_in_time: "06:45:00", check_out_time: "13:30:00", status: "on_time" },
              { date: d1, check_in_time: "07:05:00", check_out_time: "13:30:00", status: "late" },
            ],
          },
        ],
      }),
    })
    setPortalBackend(backend)

    render(<App />)
    await waitFor(() => expect(screen.getByText(/Familia Elena Mendoza/i)).toBeInTheDocument())

    // Switch to Year View
    await user.click(screen.getByRole("button", { name: /Historial \(Año\)/i }))

    // Verify Child 1 (Valeria Mendoza) KPI cards
    await waitFor(() => {
      expect(screen.getByText("66.7%")).toBeInTheDocument()
      expect(screen.getByText(/Historial Diario de Asistencia - Valeria Mendoza/i)).toBeInTheDocument()
    })

    // Calendar marks P and T rendered
    expect(screen.getAllByText("P").length).toBeGreaterThanOrEqual(2)
    expect(screen.getAllByText("T").length).toBeGreaterThanOrEqual(1)

    // Switch to sibling Mateo Mendoza
    await user.click(screen.getByRole("button", { name: /Mateo Mendoza \(5° B\)/i }))

    await waitFor(() => {
      expect(screen.getByText("50%")).toBeInTheDocument()
      expect(screen.getByText(/Historial Diario de Asistencia - Mateo Mendoza/i)).toBeInTheDocument()
    })
  })
})
