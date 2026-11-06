import React, { createContext, useContext, useEffect, useMemo, useState } from "react"
import { NotSetUpYet, SchoolSettingsUnavailable } from "@/components/SchoolSettingsMissing"
import { getPortalBackend, type SchoolSettings } from "@/lib/supabase"
import {
  formatDate,
  formatMonth,
  formatShortDate,
  formatTime,
  translate,
  type Language,
  type MessageKey,
  type MessageParams,
  type TimeOptions,
} from "@/lib/i18n"

/** Whether a calendar day is a School Day, one of the School's holidays, or a weekday it is closed. */
export type DayKind = "school_day" | "holiday" | "closed"

/** The School Settings once read: "not_set_up" until the School saves them, "unavailable" when they cannot be read. */
type LoadedSettings = SchoolSettings | "not_set_up" | "unavailable"

interface SchoolContextType {
  lang: Language
  /** Grade labels; a Grade's rank is its position in this list, counting from 1. */
  grades: string[]
  sections: string[]
  /** HH:MM:SS; check-ins after it are Late. */
  lateThreshold: string
  t: (key: MessageKey, params?: MessageParams) => string
  formatDate: (isoDate: string) => string
  formatShortDate: (isoDate: string) => string
  formatTime: (clock: string, options?: TimeOptions) => string
  formatMonth: (month: Date) => string
  gradeLabel: (rank: number) => string
  dayKind: (isoDate: string) => DayKind
}

const SchoolContext = createContext<SchoolContextType | null>(null)

function schoolContext(school: SchoolSettings): SchoolContextType {
  const lang = school.school_language
  const holidays = new Set(school.holidays)

  return {
    lang,
    grades: school.grades,
    sections: school.sections,
    lateThreshold: school.late_threshold,
    t: (key, params) => translate(lang, key, params),
    formatDate: (isoDate) => formatDate(lang, isoDate),
    formatShortDate: (isoDate) => formatShortDate(lang, isoDate),
    formatTime: (clock, options) => formatTime(lang, clock, options),
    formatMonth: (month) => formatMonth(lang, month),
    gradeLabel: (rank) => school.grades[rank - 1] ?? String(rank),
    dayKind: (isoDate) => {
      if (holidays.has(isoDate)) {
        return "holiday"
      }
      const [year, month, day] = isoDate.split("-").map(Number)
      // getDay() counts from 0 for Sunday; the School counts from 0 for Monday.
      const weekday = (new Date(year, month - 1, day).getDay() + 6) % 7
      return school.active_weekdays.includes(weekday) ? "school_day" : "closed"
    },
  }
}

/** Reads the School Settings each time the portal loads, so a new School Language shows after a refresh. */
export function SchoolProvider({ children }: { children: React.ReactNode }) {
  const [loaded, setLoaded] = useState<LoadedSettings | null>(null)

  useEffect(() => {
    let isMounted = true
    getPortalBackend()
      .fetchSchoolSettings()
      .then(
        (settings): LoadedSettings => settings ?? "not_set_up",
        (err): LoadedSettings => {
          console.error("Error loading the School Settings:", err)
          return "unavailable"
        }
      )
      .then((settings) => {
        if (isMounted) setLoaded(settings)
      })
    return () => {
      isMounted = false
    }
  }, [])

  const value = useMemo(() => (loaded && typeof loaded === "object" ? schoolContext(loaded) : null), [loaded])

  useEffect(() => {
    if (!value) return
    document.documentElement.lang = value.lang
    document.title = value.t("app.title")
  }, [value])

  if (loaded === "not_set_up") {
    return <NotSetUpYet />
  }
  if (loaded === "unavailable") {
    return <SchoolSettingsUnavailable />
  }
  if (!value) {
    return (
      <div className="flex h-screen w-screen items-center justify-center bg-slate-50">
        <div className="h-8 w-8 animate-spin rounded-full border-4 border-blue-600 border-t-transparent" />
      </div>
    )
  }

  return <SchoolContext.Provider value={value}>{children}</SchoolContext.Provider>
}

export function useSchool() {
  const ctx = useContext(SchoolContext)
  if (!ctx) throw new Error("useSchool must be used within a SchoolProvider")
  return ctx
}
