import { vi } from "vitest"
import type { DayViewData, PortalBackend, SchoolSettings, YearViewData } from "@/lib/supabase"

/** A Spanish-speaking School whose Grade labels read like their ranks. */
export const spanishSchool: SchoolSettings = {
  school_language: "es",
  grades: ["1°", "2°", "3°", "4°", "5°", "6°", "7°", "8°", "9°", "10°", "11°"],
  sections: ["A", "B", "C", "D"],
  active_weekdays: [0, 1, 2, 3, 4],
  holidays: [],
  late_threshold: "06:50:00",
}

/** An English-speaking School whose Grade labels differ from their ranks. */
export const englishSchool: SchoolSettings = {
  school_language: "en",
  grades: ["Kindergarten", "Grade 1", "Grade 2", "Grade 3", "Grade 4", "Grade 5"],
  sections: ["Blue", "Green"],
  active_weekdays: [0, 1, 2, 3, 4],
  holidays: [],
  late_threshold: "07:15:00",
}

export const emptyDayView: DayViewData = {
  date: "2026-10-16",
  summary: { total_enrolled: 0, present_today: 0, late_today: 0, absent_today: 0, attendance_rate: 100 },
  students: [],
}

export const emptyYearView: YearViewData = {
  total_students: 0,
  summary: { total_students: 0, total_present_days: 0, total_late_days: 0, total_absent_days: 0, average_punctuality: 100 },
  students: [],
}

/** A backend for a Spanish-speaking School with nobody signed in and no attendance, unless overridden. */
export function mockBackend(overrides: Partial<PortalBackend> = {}): PortalBackend {
  return {
    fetchSchoolSettings: vi.fn().mockResolvedValue(spanishSchool),
    getCurrentSessionProfile: vi.fn().mockResolvedValue(null),
    onAuthStateChange: vi.fn().mockReturnValue(() => {}),
    signInWithPassword: vi.fn(),
    signUpFirstTime: vi.fn(),
    signInWithGoogle: vi.fn(),
    signOut: vi.fn().mockResolvedValue(undefined),
    fetchDayView: vi.fn().mockResolvedValue(emptyDayView),
    fetchYearView: vi.fn().mockResolvedValue(emptyYearView),
    ...overrides,
  }
}

type HttpReply = { status: number; body: unknown }

/** Replaces the network under the Supabase client, recording every request it makes. */
export function stubSupabaseHttp(reply: (url: URL, body: unknown) => HttpReply) {
  const requests: Array<{ url: URL; body: unknown }> = []
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = new URL(input instanceof Request ? input.url : String(input))
      const body = typeof init?.body === "string" ? JSON.parse(init.body) : undefined
      requests.push({ url, body })
      const { status, body: replyBody } = reply(url, body)
      return new Response(JSON.stringify(replyBody), { status, headers: { "Content-Type": "application/json" } })
    })
  )
  return requests
}
