import { createClient, type SupabaseClient } from "@supabase/supabase-js"
import type { UserProfile } from "@/context/AuthContext"
import { isLanguage, type Language } from "@/lib/i18n"
import { localToday } from "@/lib/utils"

const supabaseUrl = import.meta.env.VITE_SUPABASE_URL || "http://localhost:54321"
const supabaseAnonKey = import.meta.env.VITE_SUPABASE_ANON_KEY || "sb_publishable_placeholder"

export const supabase: SupabaseClient = createClient(supabaseUrl, supabaseAnonKey, {
  auth: {
    persistSession: true,
    autoRefreshToken: true,
    detectSessionInUrl: true,
  },
})

/** Filter value meaning "every Grade" or "every Section"; screens choose their own label for it. */
export const ALL = "ALL"

/** Raised by the database when an email is not an Authorized Email; screens show their own text for it. */
export const ERR_UNAUTHORIZED_EMAIL = "ERR_UNAUTHORIZED_EMAIL"

/** How the School is set up, as `get_school_settings()` returns it. */
export interface SchoolSettings {
  school_language: Language
  /** Grade labels; a Grade's rank is its position in this list, counting from 1. */
  grades: string[]
  sections: string[]
  /** The weekdays with classes, from 0 for Monday to 6 for Sunday. */
  active_weekdays: number[]
  /** Dates without classes, as YYYY-MM-DD. */
  holidays: string[]
  /** HH:MM:SS; check-ins after it are Late. */
  late_threshold: string
}

export interface DayViewStudent {
  student_id: number
  name: string
  badge_uid: string
  role?: string
  grade: number
  section: string
  family_id: string
  check_in_time: string | null
  check_out_time: string | null
  /** "no_classes" for a Student without a Check-in on a day the School has no classes. */
  status: "on_time" | "late" | "departed" | "absent" | "no_classes"
  punctuality: "on_time" | "late" | "absent"
  departed: boolean
}

export interface DayViewData {
  date: string
  family_id?: string
  grade?: number
  summary: {
    total_enrolled: number
    total_students?: number
    present_today: number
    late_today: number
    absent_today: number
    /** Null on a day the School has no classes. */
    attendance_rate: number | null
  }
  students: DayViewStudent[]
}

export interface YearViewStudent {
  student_id: number
  name: string
  badge_uid?: string
  role?: string
  grade: number
  section: string
  family_id?: string
  present_days: number
  late_days: number
  absent_days: number
  punctuality_rate: number
  metrics: {
    present_days: number
    late_days: number
    absent_days: number
    punctuality_rate: number
  }
  days: Record<string, "P" | "T" | "A">
  history: Array<{
    date: string
    check_in_time: string | null
    check_out_time: string | null
    checkin_status?: "on_time" | "late" | "absent"
    status: "on_time" | "late" | "departed" | "absent"
  }>
}

export interface YearViewData {
  family_id?: string
  grade?: number
  total_school_days?: number
  total_students: number
  school_dates?: string[]
  summary: {
    total_students: number
    total_present_days: number
    total_late_days: number
    total_absent_days: number
    average_punctuality: number
  }
  students: YearViewStudent[]
}

export interface FetchDayViewParams {
  date?: string
  grade?: number
  section?: string
  search?: string
  familyCode?: string
  familyId?: string
  /** False on a holiday or a weekday without classes: nobody without a Check-in is absent then. */
  schoolDay?: boolean
}

export interface FetchYearViewParams {
  startDate?: string
  endDate?: string
  studentId?: number
  grade?: number
  section?: string
  search?: string
}

export interface PortalBackend {
  /** The School Settings, or null until the School has saved them. */
  fetchSchoolSettings: () => Promise<SchoolSettings | null>
  getCurrentSessionProfile: () => Promise<UserProfile | null>
  onAuthStateChange: (callback: (profile: UserProfile | null) => void) => () => void
  signInWithPassword: (email: string, password: string) => Promise<UserProfile>
  signUpFirstTime: (email: string, password: string, challengeValue?: string) => Promise<UserProfile>
  signInWithGoogle: () => Promise<UserProfile | null>
  signOut: () => Promise<void>
  fetchDayView: (params?: FetchDayViewParams) => Promise<DayViewData>
  fetchYearView: (params?: FetchYearViewParams) => Promise<YearViewData>
}

// Supabase hands back errors either as Error instances or as plain
// { message, code, details } objects, depending on the client call.
function errorField(err: unknown, field: "message" | "code"): string {
  if (err && typeof err === "object" && field in err) {
    return String((err as Record<string, unknown>)[field] ?? "")
  }
  return field === "message" ? String(err) : ""
}

function isUnauthorizedEmailError(err: unknown): boolean {
  const message = errorField(err, "message")
  return (
    message === ERR_UNAUTHORIZED_EMAIL ||
    errorField(err, "code") === ERR_UNAUTHORIZED_EMAIL ||
    // Supabase Auth's reply when the Authorized Email trigger rejects a sign-up.
    message.includes("Database error saving new user")
  )
}

function normalizeAuthorizedEmailError(err: unknown): Error {
  if (isUnauthorizedEmailError(err)) {
    return new Error(ERR_UNAUTHORIZED_EMAIL)
  }
  return err instanceof Error ? err : new Error(errorField(err, "message"))
}

/** The Section to filter by, or null when every Section is wanted. Sections match in any letter case. */
function sectionFilter(section: string | undefined): string | null {
  const value = section?.trim().toUpperCase() ?? ""
  return value === "" || value === ALL ? null : value
}

function isSchoolSettings(data: unknown): data is SchoolSettings {
  return typeof data === "object" && data !== null && isLanguage((data as SchoolSettings).school_language)
}

async function resolveWebAccount(): Promise<UserProfile> {
  const { data, error } = await supabase.rpc("get_web_account")
  if (error || !data) {
    throw normalizeAuthorizedEmailError(error || new Error("No Web Account was returned for this session."))
  }
  return data as UserProfile
}

export function computeStudentDayStatus(records: Array<{ event_type: string; time: string; status: string | null }>): {
  check_in_time: string | null
  check_out_time: string | null
  status: "on_time" | "late" | "departed" | "absent"
  is_present: boolean
  is_late: boolean
} {
  const checkIn = records.find((r) => r.event_type === "check_in")
  const checkOut = records.find((r) => r.event_type === "check_out")
  const checkInTime = checkIn ? checkIn.time : null
  const checkOutTime = checkOut ? checkOut.time : null

  let status: "on_time" | "late" | "departed" | "absent" = "absent"
  if (checkOut) {
    status = "departed"
  } else if (checkIn) {
    status = checkIn.status === "late" ? "late" : "on_time"
  }

  return {
    check_in_time: checkInTime,
    check_out_time: checkOutTime,
    status,
    is_present: Boolean(checkIn),
    is_late: Boolean(checkIn && checkIn.status === "late"),
  }
}

const defaultPortalBackend: PortalBackend = {
  async fetchSchoolSettings() {
    const { data, error } = await supabase.rpc("get_school_settings")
    if (error) {
      throw new Error(error.message)
    }
    return isSchoolSettings(data) ? data : null
  },

  async getCurrentSessionProfile() {
    const { data, error } = await supabase.auth.getSession()
    if (error || !data.session) {
      return null
    }
    return await resolveWebAccount()
  },

  onAuthStateChange(callback) {
    const {
      data: { subscription },
    } = supabase.auth.onAuthStateChange(async (event, session) => {
      if (event === "SIGNED_OUT" || !session) {
        callback(null)
        return
      }
      if (event === "SIGNED_IN" || event === "TOKEN_REFRESHED") {
        try {
          const account = await resolveWebAccount()
          callback(account)
        } catch {
          callback(null)
        }
      }
    })
    return () => subscription.unsubscribe()
  },

  async signInWithPassword(email: string, password: string) {
    const { error } = await supabase.auth.signInWithPassword({
      email: email.trim(),
      password,
    })
    if (error) {
      throw normalizeAuthorizedEmailError(error)
    }
    return await resolveWebAccount()
  },

  async signUpFirstTime(email: string, password: string) {
    const { data, error } = await supabase.auth.signUp({
      email: email.trim(),
      password,
    })
    if (error) {
      throw normalizeAuthorizedEmailError(error)
    }
    if (!data.session) {
      const signInRes = await supabase.auth.signInWithPassword({
        email: email.trim(),
        password,
      })
      if (signInRes.error) {
        throw normalizeAuthorizedEmailError(signInRes.error)
      }
    }
    return await resolveWebAccount()
  },

  async signInWithGoogle() {
    const { error } = await supabase.auth.signInWithOAuth({
      provider: "google",
      options: {
        redirectTo: window.location.origin,
      },
    })
    if (error) {
      throw normalizeAuthorizedEmailError(error)
    }
    return null
  },

  async signOut() {
    await supabase.auth.signOut()
  },

  async fetchDayView(params: FetchDayViewParams = {}) {
    const targetDate = params.date || localToday()
    const schoolDay = params.schoolDay ?? true
    const familyFilter = params.familyCode || params.familyId

    let studentQuery = supabase
      .from("student_details")
      .select("user_id, grade, section, family_id, users!inner(id, full_name, badge_uid, role, is_active)")
      .eq("users.is_active", true)
      .eq("users.role", "student")

    if (params.grade !== undefined) {
      studentQuery = studentQuery.eq("grade", params.grade)
    }
    if (familyFilter) {
      studentQuery = studentQuery.eq("family_id", familyFilter)
    }

    const section = sectionFilter(params.section)
    const searchTerm = params.search?.trim().toLowerCase() || ""
    const shouldSearchStaff = Boolean(searchTerm && params.grade === undefined && !familyFilter)

    const [studentsRes, recordsRes, staffRes] = await Promise.all([
      studentQuery,
      supabase
        .from("attendance_records")
        .select("id, event_type, date, time, status, badge_uid, user_id, name, role, grade, section")
        .eq("date", targetDate)
        .order("time", { ascending: true }),
      shouldSearchStaff
        ? supabase
            .from("users")
            .select("id, full_name, badge_uid, role, is_active")
            .eq("is_active", true)
            .neq("role", "student")
        : Promise.resolve({ data: [], error: null }),
    ])

    if (studentsRes.error) throw new Error(studentsRes.error.message)
    if (recordsRes.error) throw new Error(recordsRes.error.message)

    const rawStudents = (studentsRes.data || []) as Array<any>
    const rawStaff = (staffRes.data || []) as Array<any>
    const rawRecords = (recordsRes.data || []) as Array<{
      id: number
      event_type: string
      date: string
      time: string
      status: string | null
      badge_uid: string
      user_id: number | null
    }>

    const combinedRoster = [
      ...rawStudents.map((row) => {
        const u = Array.isArray(row.users) ? row.users[0] : row.users
        return {
          user_id: Number(row.user_id),
          name: String(u?.full_name || ""),
          badge_uid: String(u?.badge_uid || ""),
          role: String(u?.role || "student"),
          grade: Number(row.grade),
          section: String(row.section),
          family_id: String(row.family_id || ""),
        }
      }),
      ...rawStaff.map((u) => ({
        user_id: Number(u.id),
        name: String(u.full_name || ""),
        badge_uid: String(u.badge_uid || ""),
        role: String(u.role || "staff"),
        grade: 0,
        section: "-",
        family_id: "STAFF",
      })),
    ]

    const filteredRoster = combinedRoster
      .filter((s) => !section || s.section.toUpperCase() === section)
      .filter((s) => {
        if (!searchTerm) return true
        return (
          s.name.toLowerCase().includes(searchTerm) ||
          s.badge_uid.toLowerCase().includes(searchTerm) ||
          (s.family_id && s.family_id.toLowerCase().includes(searchTerm))
        )
      })
      .sort((a, b) => a.grade - b.grade || a.section.localeCompare(b.section) || a.name.localeCompare(b.name))

    let presentCount = 0
    let lateCount = 0
    let absentCount = 0

    const studentItems: DayViewStudent[] = filteredRoster.map((st) => {
      const stRecords = rawRecords.filter(
        (r) => r.user_id === st.user_id || r.badge_uid.toUpperCase() === st.badge_uid.toUpperCase()
      )
      const computed = computeStudentDayStatus(stRecords)
      if (computed.is_present) {
        presentCount += 1
        if (computed.is_late) lateCount += 1
      } else if (schoolDay) {
        absentCount += 1
      }

      return {
        student_id: st.user_id,
        name: st.name,
        badge_uid: st.badge_uid,
        role: st.role,
        grade: st.grade,
        section: st.section,
        family_id: st.family_id,
        check_in_time: computed.check_in_time,
        check_out_time: computed.check_out_time,
        status: computed.is_present || schoolDay ? computed.status : "no_classes",
        punctuality: computed.is_late ? "late" : computed.is_present ? "on_time" : "absent",
        departed: computed.check_out_time !== null,
      }
    })

    const totalEnrolled = studentItems.length
    const attendanceRate = !schoolDay
      ? null
      : totalEnrolled > 0
      ? Math.round((presentCount / totalEnrolled) * 1000) / 10
      : 100

    return {
      date: targetDate,
      family_id: familyFilter || studentItems[0]?.family_id,
      grade: params.grade || studentItems[0]?.grade,
      summary: {
        total_enrolled: totalEnrolled,
        total_students: totalEnrolled,
        present_today: presentCount,
        late_today: lateCount,
        absent_today: absentCount,
        attendance_rate: attendanceRate,
      },
      students: studentItems,
    }
  },

  async fetchYearView(params: FetchYearViewParams = {}) {
    const { data, error } = await supabase.rpc("get_year_view_stats", {
      p_date_start: params.startDate || null,
      p_date_end: params.endDate || null,
      p_student_id: params.studentId ?? null,
      p_grade: params.grade ?? null,
      p_section: sectionFilter(params.section),
    })

    if (error) {
      throw new Error(error.message)
    }

    const result = data as YearViewData
    const searchTerm = params.search?.trim().toLowerCase() || ""
    if (!searchTerm) {
      return result
    }

    const filtered = (result.students || []).filter(
      (st) =>
        st.name.toLowerCase().includes(searchTerm) ||
        (st.badge_uid && st.badge_uid.toLowerCase().includes(searchTerm)) ||
        (st.family_id && st.family_id.toLowerCase().includes(searchTerm))
    )
    return {
      ...result,
      total_students: filtered.length,
      students: filtered,
    }
  },
}

let activeBackend: PortalBackend = defaultPortalBackend

export function getPortalBackend(): PortalBackend {
  return activeBackend
}

export function setPortalBackend(customBackend: PortalBackend): void {
  activeBackend = customBackend
}

export function resetPortalBackend(): void {
  activeBackend = defaultPortalBackend
}
