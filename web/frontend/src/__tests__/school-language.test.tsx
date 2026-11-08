import { describe, it, expect, beforeEach, afterEach, vi } from "vitest"
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { exportRows } from "@/lib/spreadsheet"
import { App } from "@/App"
import {
  ERR_UNAUTHORIZED_EMAIL,
  getPortalBackend,
  resetPortalBackend,
  setPortalBackend,
  type DayViewData,
  type DayViewStudent,
  type YearViewData,
} from "@/lib/supabase"
import type { UserProfile } from "@/context/AuthContext"
import { emptyYearView, englishSchool, mockBackend, spanishSchool, stubSupabaseHttp } from "./support"

vi.mock("@/lib/spreadsheet", () => ({ exportRows: vi.fn() }))

const teacher: UserProfile = {
  id: 20,
  email: "laura.solis@school.edu",
  role: "teacher",
  name: "Laura Solis",
  linked_entity_id: "20",
  details: { taught_grade: 6, badge_uid: "T6" },
}

const admin: UserProfile = {
  id: 30,
  email: "director@school.edu",
  role: "admin",
  name: "Director General",
  linked_entity_id: "30",
  details: { badge_uid: "ADM1" },
}

const guardian: UserProfile = {
  id: 10,
  email: "elena.mendoza@school.edu",
  role: "guardian",
  name: "Elena Mendoza",
  linked_entity_id: "FAM-5001",
  details: { family_id: "FAM-5001", children: [] },
}

function student(overrides: Partial<DayViewStudent>): DayViewStudent {
  return {
    student_id: 101,
    name: "Valeria Mendoza",
    badge_uid: "UID_VAL01",
    grade: 6,
    section: "Blue",
    family_id: "FAM-5001",
    check_in_time: null,
    check_out_time: null,
    status: "absent",
    punctuality: "absent",
    departed: false,
    ...overrides,
  }
}

function dayView(students: DayViewStudent[]): DayViewData {
  return {
    date: "2026-10-16",
    grade: 6,
    summary: { total_enrolled: students.length, present_today: 2, late_today: 1, absent_today: 0, attendance_rate: 100 },
    students,
  }
}

const lateAfterLunch = student({ check_in_time: "13:05:09", status: "late", punctuality: "late" })
const earlyBird = student({
  student_id: 102,
  name: "Mateo Mendoza",
  badge_uid: "UID_MAT02",
  section: "Green",
  check_in_time: "06:40:00",
  status: "on_time",
  punctuality: "on_time",
})

beforeEach(() => {
  localStorage.clear()
  resetPortalBackend()
  vi.clearAllMocks()
})

afterEach(() => {
  vi.unstubAllGlobals()
  resetPortalBackend()
})

describe("The portal never guesses the School Language", () => {
  it("stops with English setup steps until the School saves its settings", async () => {
    window.history.pushState({}, "", "/login")
    setPortalBackend(mockBackend({ fetchSchoolSettings: vi.fn().mockResolvedValue(null) }))

    render(<App />)

    expect(await screen.findByRole("heading", { name: "Quickpass is not set up yet" })).toBeInTheDocument()
    expect(screen.getByText(/finish its setup wizard, where the School chooses its School Language/)).toBeInTheDocument()
    expect(screen.queryByText("Sign In")).not.toBeInTheDocument()
    expect(screen.queryByText("Iniciar Sesión")).not.toBeInTheDocument()
  })

  it("says in every language that the School Settings could not be loaded", async () => {
    const consoleError = vi.spyOn(console, "error").mockImplementation(() => {})
    setPortalBackend(mockBackend({ fetchSchoolSettings: vi.fn().mockRejectedValue(new Error("Failed to fetch")) }))

    render(<App />)

    expect(await screen.findByText("The School Settings could not be loaded. Check the connection and refresh the page.")).toBeInTheDocument()
    expect(screen.getByText("No se pudo cargar la configuración del colegio. Revise la conexión y actualice la página.")).toBeInTheDocument()
    expect(screen.queryByText("Sign In")).not.toBeInTheDocument()
    consoleError.mockRestore()
  })
})

describe("The portal speaks the School Language", () => {
  it("greets the visitors of an English-speaking School in English", async () => {
    window.history.pushState({}, "", "/login")
    setPortalBackend(mockBackend({ fetchSchoolSettings: vi.fn().mockResolvedValue(englishSchool) }))

    render(<App />)

    expect(await screen.findByText("Sign In")).toBeInTheDocument()
    expect(screen.getByLabelText("Registered Email")).toBeInTheDocument()
    expect(screen.getByRole("button", { name: "Sign in with Email" })).toBeInTheDocument()
    expect(screen.queryByText("Iniciar Sesión")).not.toBeInTheDocument()
    expect(document.documentElement.lang).toBe("en")
  })

  it("names an unregistered email by its error code, in the School Language", async () => {
    const user = userEvent.setup()
    window.history.pushState({}, "", "/login")
    setPortalBackend(
      mockBackend({
        fetchSchoolSettings: vi.fn().mockResolvedValue(englishSchool),
        signUpFirstTime: vi.fn().mockRejectedValue(new Error(ERR_UNAUTHORIZED_EMAIL)),
      })
    )

    render(<App />)
    await user.click(await screen.findByRole("button", { name: "First time? Activate" }))
    await user.type(screen.getByLabelText("Authorized Email"), "intruder@outsider.org")
    await user.type(screen.getByLabelText("New Password"), "Secret123!")
    await user.type(screen.getByLabelText("Confirm Password"), "Secret123!")
    await user.click(screen.getByRole("button", { name: "Create Password & Sign In" }))

    expect(
      await screen.findByText("This email is not registered in the school system. Please contact the school administration.")
    ).toBeInTheDocument()
    expect(screen.queryByText(ERR_UNAUTHORIZED_EMAIL)).not.toBeInTheDocument()
  })

  it("writes a Spanish School's dates as DD/MM/YYYY and its times on the 24-hour clock", async () => {
    window.history.pushState({}, "", "/teacher")
    setPortalBackend(
      mockBackend({
        getCurrentSessionProfile: vi.fn().mockResolvedValue(teacher),
        fetchDayView: vi.fn().mockResolvedValue(dayView([lateAfterLunch, earlyBird])),
      })
    )

    render(<App />)

    expect(await screen.findByText("Nómina de Asistencia de Hoy (16/10/2026)")).toBeInTheDocument()
    expect(screen.getByText("13:05:09")).toBeInTheDocument()
    expect(screen.getByText("06:40:00")).toBeInTheDocument()
    expect(screen.getByText("Grado Asignado: 6°")).toBeInTheDocument()
    expect(screen.getByText("Tarde")).toBeInTheDocument()
    expect(screen.getByText("Puntual")).toBeInTheDocument()
    expect(document.documentElement.lang).toBe("es")
  })

  it("writes an English School's dates as MM/DD/YYYY and its times on the 12-hour clock", async () => {
    window.history.pushState({}, "", "/teacher")
    setPortalBackend(
      mockBackend({
        fetchSchoolSettings: vi.fn().mockResolvedValue(englishSchool),
        getCurrentSessionProfile: vi.fn().mockResolvedValue(teacher),
        fetchDayView: vi.fn().mockResolvedValue(dayView([lateAfterLunch, earlyBird])),
      })
    )

    render(<App />)

    expect(await screen.findByText("Today's Attendance Roster (10/16/2026)")).toBeInTheDocument()
    expect(screen.getByText("01:05:09 PM")).toBeInTheDocument()
    expect(screen.getByText("06:40:00 AM")).toBeInTheDocument()
    expect(screen.getByText("Assigned Grade: Grade 5")).toBeInTheDocument()
    expect(screen.getByText("Late")).toBeInTheDocument()
    expect(screen.getByText("On Time")).toBeInTheDocument()
    expect(screen.getByRole("button", { name: /Day View/ })).toBeInTheDocument()
    expect(screen.getByRole("button", { name: /Year View/ })).toBeInTheDocument()
    expect(screen.getByTitle("Sign out")).toBeInTheDocument()
  })

  it("names exported matrices with the School's Grade label, in the School Language", async () => {
    const user = userEvent.setup()
    window.history.pushState({}, "", "/teacher")
    const yearView: YearViewData = {
      ...emptyYearView,
      grade: 6,
      total_students: 1,
      students: [
        {
          student_id: 101,
          name: "Valeria Mendoza",
          grade: 6,
          section: "Blue",
          present_days: 3,
          late_days: 1,
          absent_days: 0,
          punctuality_rate: 66.7,
          metrics: { present_days: 3, late_days: 1, absent_days: 0, punctuality_rate: 66.7 },
          days: {},
          history: [],
        },
      ],
    }
    setPortalBackend(
      mockBackend({
        fetchSchoolSettings: vi.fn().mockResolvedValue(englishSchool),
        getCurrentSessionProfile: vi.fn().mockResolvedValue(teacher),
        fetchYearView: vi.fn().mockResolvedValue(yearView),
      })
    )

    render(<App />)
    await user.click(await screen.findByRole("button", { name: /Year View/ }))
    await user.click(await screen.findByRole("button", { name: "Export Matrix (.xlsx)" }))

    expect(exportRows).toHaveBeenCalledWith(expect.anything(), expect.objectContaining({ fileName: "Attendance_Matrix_Grade 5.xlsx" }))
  })

  it("reads the School Language afresh each time the portal opens", async () => {
    window.history.pushState({}, "", "/login")
    setPortalBackend(
      mockBackend({
        fetchSchoolSettings: vi.fn().mockResolvedValueOnce(spanishSchool).mockResolvedValueOnce(englishSchool),
      })
    )

    const firstVisit = render(<App />)
    expect(await screen.findByText("Iniciar Sesión")).toBeInTheDocument()
    firstVisit.unmount()

    render(<App />)
    expect(await screen.findByText("Sign In")).toBeInTheDocument()
  })

  it("reads the School Settings from Supabase, and none before the School has saved them", async () => {
    let saved: unknown = englishSchool
    const requests = stubSupabaseHttp(() => ({ status: 200, body: saved }))

    expect(await getPortalBackend().fetchSchoolSettings()).toEqual(englishSchool)
    saved = null
    expect(await getPortalBackend().fetchSchoolSettings()).toBeNull()

    expect(requests.map((r) => r.url.pathname)).toEqual([
      "/rest/v1/rpc/get_school_settings",
      "/rest/v1/rpc/get_school_settings",
    ])
  })
})

describe("Filters offer the School's own Grades and Sections", () => {
  function optionTexts(select: HTMLElement): string[] {
    return within(select)
      .getAllByRole("option")
      .map((option) => option.textContent ?? "")
  }

  it("lists the School's Grade labels and Sections in the Admin filters", async () => {
    const user = userEvent.setup()
    window.history.pushState({}, "", "/admin")
    const fetchDayView = vi.fn().mockResolvedValue(dayView([]))
    setPortalBackend(
      mockBackend({
        fetchSchoolSettings: vi.fn().mockResolvedValue(englishSchool),
        getCurrentSessionProfile: vi.fn().mockResolvedValue(admin),
        fetchDayView,
      })
    )

    render(<App />)
    const gradeFilter = await screen.findByRole("combobox", { name: "Grade" })
    const sectionFilter = screen.getByRole("combobox", { name: "Section" })

    expect(optionTexts(gradeFilter)).toEqual(["All Grades", ...englishSchool.grades])
    expect(optionTexts(sectionFilter)).toEqual(["All Sections", "Section Blue", "Section Green"])

    await user.selectOptions(gradeFilter, "Grade 1")
    await waitFor(() => expect(fetchDayView).toHaveBeenLastCalledWith(expect.objectContaining({ grade: 2 })))
    await user.selectOptions(sectionFilter, "Section Green")
    await waitFor(() =>
      expect(fetchDayView).toHaveBeenLastCalledWith(expect.objectContaining({ grade: 2, section: "Green" }))
    )
  })

  it("gives the Teacher one button for each of the School's Sections", async () => {
    const user = userEvent.setup()
    window.history.pushState({}, "", "/teacher")
    const fetchDayView = vi.fn().mockResolvedValue(dayView([]))
    setPortalBackend(
      mockBackend({
        fetchSchoolSettings: vi.fn().mockResolvedValue(englishSchool),
        getCurrentSessionProfile: vi.fn().mockResolvedValue(teacher),
        fetchDayView,
      })
    )

    render(<App />)
    await user.click(await screen.findByRole("button", { name: "Green" }))

    expect(screen.getByRole("button", { name: "All" })).toBeInTheDocument()
    expect(screen.getByRole("button", { name: "Blue" })).toBeInTheDocument()
    expect(screen.queryByRole("button", { name: "A" })).not.toBeInTheDocument()
    await waitFor(() =>
      expect(fetchDayView).toHaveBeenLastCalledWith(expect.objectContaining({ grade: 6, section: "Green" }))
    )
  })

  it("lets an Admin view the portal as the Teacher of any of the School's Grades", async () => {
    const user = userEvent.setup()
    window.history.pushState({}, "", "/teacher")
    const fetchDayView = vi.fn().mockResolvedValue(dayView([]))
    setPortalBackend(
      mockBackend({
        fetchSchoolSettings: vi.fn().mockResolvedValue(englishSchool),
        getCurrentSessionProfile: vi.fn().mockResolvedValue(admin),
        fetchDayView,
      })
    )

    render(<App />)
    const gradeSelect = await screen.findByRole("combobox", { name: "Select grade" })
    expect(optionTexts(gradeSelect)).toEqual(englishSchool.grades)

    await user.selectOptions(gradeSelect, "Kindergarten")

    expect(await screen.findByText("Simulating Kindergarten")).toBeInTheDocument()
    await waitFor(() => expect(fetchDayView).toHaveBeenLastCalledWith(expect.objectContaining({ grade: 1 })))
  })

  it("matches the Day View's Section whatever its letter case", async () => {
    stubSupabaseHttp((url) =>
      url.pathname.endsWith("/student_details")
        ? {
            status: 200,
            body: [
              { user_id: 1, grade: 6, section: "Blue", family_id: "F1", users: { id: 1, full_name: "Ana", badge_uid: "A1", role: "student", is_active: true } },
              { user_id: 2, grade: 6, section: "GREEN", family_id: "F2", users: { id: 2, full_name: "Leo", badge_uid: "B2", role: "student", is_active: true } },
            ],
          }
        : { status: 200, body: [] }
    )

    const blue = await getPortalBackend().fetchDayView({ date: "2026-10-16", grade: 6, section: "BLUE" })
    const green = await getPortalBackend().fetchDayView({ date: "2026-10-16", grade: 6, section: "Green" })

    expect(blue.students.map((s) => s.name)).toEqual(["Ana"])
    expect(green.students.map((s) => s.name)).toEqual(["Leo"])
  })
})

describe("Nobody is absent on a day without classes", () => {
  const localToday = () => {
    const now = new Date()
    return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-${String(now.getDate()).padStart(2, "0")}`
  }
  const usDate = (isoDate: string) => {
    const [year, month, day] = isoDate.split("-")
    return `${month}/${day}/${year}`
  }

  it("counts Students without a Check-in absent only on a School Day", async () => {
    stubSupabaseHttp((url) =>
      url.pathname.endsWith("/student_details")
        ? {
            status: 200,
            body: [{ user_id: 1, grade: 6, section: "Blue", family_id: "F1", users: { id: 1, full_name: "Ana", badge_uid: "A1", role: "student", is_active: true } }],
          }
        : { status: 200, body: [] }
    )

    const schoolDay = await getPortalBackend().fetchDayView({ date: "2026-10-16" })
    const holiday = await getPortalBackend().fetchDayView({ date: "2026-10-16", schoolDay: false })

    expect(schoolDay.students[0].status).toBe("absent")
    expect(schoolDay.summary).toMatchObject({ absent_today: 1, attendance_rate: 0 })
    expect(holiday.students[0].status).toBe("no_classes")
    expect(holiday.summary).toMatchObject({ absent_today: 0, attendance_rate: null })
  })

  it("tells the Teacher that today is a holiday", async () => {
    const today = localToday()
    const fetchDayView = vi.fn().mockResolvedValue({ ...dayView([student({ status: "no_classes" })]), date: today })
    window.history.pushState({}, "", "/teacher")
    setPortalBackend(
      mockBackend({
        fetchSchoolSettings: vi.fn().mockResolvedValue({ ...englishSchool, holidays: [today] }),
        getCurrentSessionProfile: vi.fn().mockResolvedValue(teacher),
        fetchDayView,
      })
    )

    render(<App />)

    expect(await screen.findByText(`${usDate(today)} is a holiday: nobody is marked absent.`)).toBeInTheDocument()
    expect(screen.getByText("No Classes")).toBeInTheDocument()
    expect(fetchDayView).toHaveBeenCalledWith(expect.objectContaining({ date: today, schoolDay: false }))
  })

  it("tells the Admin when the School has no classes on the date chosen", async () => {
    const fetchDayView = vi.fn(async (params?: { date?: string }) => ({ ...dayView([]), date: params?.date ?? localToday() }))
    window.history.pushState({}, "", "/admin")
    setPortalBackend(
      mockBackend({
        fetchSchoolSettings: vi.fn().mockResolvedValue(englishSchool),
        getCurrentSessionProfile: vi.fn().mockResolvedValue(admin),
        fetchDayView,
      })
    )

    render(<App />)
    fireEvent.change(await screen.findByLabelText("Query Date"), { target: { value: "2026-10-17" } })

    expect(await screen.findByText("The School has no classes on 10/17/2026: nobody is marked absent.")).toBeInTheDocument()
    expect(fetchDayView).toHaveBeenLastCalledWith(expect.objectContaining({ date: "2026-10-17", schoolDay: false }))
  })
})

describe("The Guardian calendar sets apart the days without school", () => {
  it("marks holidays and the weekdays the School is closed differently from School Days", async () => {
    const user = userEvent.setup()
    const today = new Date()
    const year = today.getFullYear()
    const month = today.getMonth()
    const isoDay = (day: number) =>
      `${year}-${String(month + 1).padStart(2, "0")}-${String(day).padStart(2, "0")}`
    const firstSaturday = 1 + ((6 - new Date(year, month, 1).getDay() + 7) % 7)
    const firstMonday = 1 + ((8 - new Date(year, month, 1).getDay()) % 7)
    window.history.pushState({}, "", "/guardian")
    setPortalBackend(
      mockBackend({
        fetchSchoolSettings: vi.fn().mockResolvedValue({ ...englishSchool, holidays: [isoDay(15)] }),
        getCurrentSessionProfile: vi.fn().mockResolvedValue(guardian),
        fetchYearView: vi.fn().mockResolvedValue({
          ...emptyYearView,
          family_id: "FAM-5001",
          total_students: 1,
          students: [
            {
              student_id: 101,
              name: "Valeria Mendoza",
              grade: 6,
              section: "Blue",
              present_days: 0,
              late_days: 1,
              absent_days: 0,
              punctuality_rate: 0,
              metrics: { present_days: 0, late_days: 1, absent_days: 0, punctuality_rate: 0 },
              days: { [isoDay(firstMonday)]: "T" },
              history: [{ date: isoDay(firstMonday), check_in_time: "07:20:00", check_out_time: null, status: "late" }],
            },
          ],
        } satisfies YearViewData),
      })
    )

    render(<App />)
    await user.click(await screen.findByRole("button", { name: /Year View/ }))

    expect(await screen.findByTitle("Holiday")).toHaveTextContent("15")
    expect(screen.getAllByTitle("No classes").map((cell) => cell.textContent)).toContain(String(firstSaturday))
    expect(screen.getByText("Holiday")).toBeInTheDocument()
    expect(screen.getByText("No classes")).toBeInTheDocument()

    expect(screen.getByTitle("Late Arrival")).toHaveTextContent("L")
    expect(screen.getByText(`${String(month + 1).padStart(2, "0")}/${String(firstMonday).padStart(2, "0")}/${year}`)).toBeInTheDocument()
    expect(screen.getByText("07:20:00 AM")).toBeInTheDocument()
  })
})
