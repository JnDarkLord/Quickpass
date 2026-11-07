import type { MessageKey } from "@/lib/i18n"
import type { DayViewStudent } from "@/lib/supabase"

/** A Student's day: on time, late, checked out, absent, or without classes. */
export type DayStatus = DayViewStudent["status"]

/** The catalog text for each DayStatus, on screen and in exports alike. */
export const STATUS_LABELS = {
  on_time: "status.on_time",
  late: "status.late",
  departed: "status.departed",
  absent: "status.absent",
  no_classes: "status.no_classes",
} as const satisfies Record<DayStatus, MessageKey>

export function isDayStatus(status: string): status is DayStatus {
  return Object.hasOwn(STATUS_LABELS, status)
}
