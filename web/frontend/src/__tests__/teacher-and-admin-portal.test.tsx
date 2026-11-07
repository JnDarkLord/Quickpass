import { describe, it, expect, beforeEach, vi } from "vitest"
import { render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import * as XLSX from "xlsx"
import { App } from "@/App"
import { setPortalBackend, resetPortalBackend } from "@/lib/supabase"
import type { UserProfile } from "@/context/AuthContext"
import { mockBackend } from "./support"

vi.mock("xlsx", async (importOriginal) => {
  const actual = await importOriginal<typeof import("xlsx")>()
  return {
    ...actual,
    writeFile: vi.fn(),
  }
})

const teacherProfile: UserProfile = {
  id: 20,
  email: "laura.solis@school.edu",
  role: "teacher",
  name: "Prof. Laura Solis",
  linked_entity_id: "20",
  details: { taught_grade: 5, badge_uid: "RLS_T_G5" },
}

const adminProfile: UserProfile = {
  id: 30,
  email: "director@school.edu",
  role: "admin",
  name: "Director General",
  linked_entity_id: "30",
  details: { badge_uid: "RLS_ADM1" },
}

describe("Teacher Portal and Admin Portal", () => {
  beforeEach(() => {
    localStorage.clear()
    resetPortalBackend()
    vi.clearAllMocks()
  })

  it("Teacher portal displays Grade KPIs, Section filter, name search, Year matrix, and .xlsx export", async () => {
    const user = userEvent.setup()
    window.history.pushState({}, "", "/teacher")

    const fetchDayViewMock = vi.fn().mockResolvedValue({
      date: "2026-10-16",
      grade: 5,
      summary: {
        total_enrolled: 2,
        present_today: 2,
        late_today: 1,
        absent_today: 0,
        attendance_rate: 100,
      },
      students: [
        {
          student_id: 101,
          name: "Valeria Mendoza",
          badge_uid: "UID_VAL01",
          grade: 5,
          section: "A",
          family_id: "FAM-5001",
          check_in_time: "06:40:00",
          check_out_time: null,
          status: "on_time",
          punctuality: "on_time",
          departed: false,
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
      ],
    })

    const fetchYearViewMock = vi.fn().mockResolvedValue({
      grade: 5,
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
          metrics: { present_days: 3, late_days: 1, absent_days: 0, punctuality_rate: 66.7 },
          days: {},
          history: [],
        },
      ],
    })

    const backend = mockBackend({
      getCurrentSessionProfile: vi.fn().mockResolvedValue(teacherProfile),
      fetchDayView: fetchDayViewMock,
      fetchYearView: fetchYearViewMock,
    })
    setPortalBackend(backend)

    render(<App />)

    await waitFor(() => {
      expect(screen.getByText("Valeria Mendoza")).toBeInTheDocument()
      expect(screen.getByText("Mateo Mendoza")).toBeInTheDocument()
    })

    // Filter by Section B
    await user.click(screen.getByRole("button", { name: /^B$/i }))
    await waitFor(() => {
      expect(fetchDayViewMock).toHaveBeenCalledWith(expect.objectContaining({ grade: 5, section: "B" }))
    })

    // Search by student name
    const searchInput = screen.getByPlaceholderText(/Buscar estudiante/i)
    await user.type(searchInput, "Valeria")
    await waitFor(() => {
      expect(fetchDayViewMock).toHaveBeenCalledWith(expect.objectContaining({ search: "Valeria" }))
    })

    // Switch to Year View and export .xlsx
    await user.click(screen.getByRole("button", { name: /Historial \(Año\)/i }))
    await waitFor(() => {
      expect(screen.getByText("58.4%")).toBeInTheDocument()
      expect(screen.getByText("66.7%")).toBeInTheDocument()
    })

    await user.click(screen.getByRole("button", { name: /Exportar Matriz \(\.xlsx\)/i }))
    expect(XLSX.writeFile).toHaveBeenCalledWith(
      expect.anything(),
      "Matriz_Asistencia_5°.xlsx"
    )
  })

  it("Admin portal displays school-wide KPIs, universal filters, Year View matrix with Absences, and exports .xlsx/.csv", async () => {
    const user = userEvent.setup()
    window.history.pushState({}, "", "/admin")

    const fetchDayViewMock = vi.fn().mockResolvedValue({
      date: "2026-10-16",
      summary: {
        total_enrolled: 3,
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
          check_in_time: "06:40:00",
          check_out_time: "13:30:00",
          status: "departed",
          punctuality: "on_time",
          departed: true,
        },
        {
          student_id: 103,
          name: "Carlos Rivas",
          badge_uid: "UID_CAR03",
          grade: 8,
          section: "A",
          family_id: "FAM-8002",
          check_in_time: null,
          check_out_time: null,
          status: "absent",
          punctuality: "absent",
          departed: false,
        },
      ],
    })

    const fetchYearViewMock = vi.fn().mockResolvedValue({
      total_students: 2,
      summary: {
        total_students: 2,
        total_present_days: 5,
        total_late_days: 1,
        total_absent_days: 2,
        average_punctuality: 83.3,
      },
      students: [
        {
          student_id: 101,
          name: "Valeria Mendoza",
          badge_uid: "UID_VAL01",
          grade: 5,
          section: "A",
          present_days: 3,
          late_days: 1,
          absent_days: 0,
          punctuality_rate: 66.7,
          metrics: { present_days: 3, late_days: 1, absent_days: 0, punctuality_rate: 66.7 },
          days: {},
          history: [],
        },
        {
          student_id: 103,
          name: "Carlos Rivas",
          badge_uid: "UID_CAR03",
          grade: 8,
          section: "A",
          present_days: 2,
          late_days: 0,
          absent_days: 2,
          punctuality_rate: 100.0,
          metrics: { present_days: 2, late_days: 0, absent_days: 2, punctuality_rate: 100.0 },
          days: {},
          history: [],
        },
      ],
    })

    const backend = mockBackend({
      getCurrentSessionProfile: vi.fn().mockResolvedValue(adminProfile),
      fetchDayView: fetchDayViewMock,
      fetchYearView: fetchYearViewMock,
    })
    setPortalBackend(backend)

    render(<App />)

    await waitFor(() => {
      expect(screen.getByText("66.7%")).toBeInTheDocument()
      expect(screen.getByText("Valeria Mendoza")).toBeInTheDocument()
      expect(screen.getByText("Carlos Rivas")).toBeInTheDocument()
      expect(screen.getByText("FAM-8002")).toBeInTheDocument()
    })

    // Export CSV and XLSX in Day View
    await user.click(screen.getByRole("button", { name: /Excel \(\.xlsx\)/i }))
    expect(XLSX.writeFile).toHaveBeenCalledWith(
      expect.anything(),
      expect.stringMatching(/\.xlsx$/),
      { bookType: "xlsx" }
    )

    await user.click(screen.getByRole("button", { name: /^CSV$/i }))
    expect(XLSX.writeFile).toHaveBeenCalledWith(
      expect.anything(),
      expect.stringMatching(/\.csv$/),
      { bookType: "csv" }
    )

    // Switch to Year View and verify consolidated matrix includes Ausencias and Código Familiar columns
    await user.click(screen.getByRole("button", { name: /Historial \(Año\)/i }))
    await waitFor(() => {
      expect(screen.getByRole("columnheader", { name: /Ausencias/i })).toBeInTheDocument()
      expect(screen.getByRole("columnheader", { name: /Código Familiar/i })).toBeInTheDocument()
      expect(screen.getByText("Valeria Mendoza")).toBeInTheDocument()
      expect(screen.getByText("Carlos Rivas")).toBeInTheDocument()
    })

    // Search by Family Code in Admin Portal
    const searchInput = screen.getByPlaceholderText(/FAM-XXXX/i)
    await user.clear(searchInput)
    await user.type(searchInput, "FAM-8002")
    await waitFor(() => {
      expect(fetchYearViewMock).toHaveBeenCalledWith(
        expect.objectContaining({
          search: "FAM-8002",
        })
      )
    })
  })
})
