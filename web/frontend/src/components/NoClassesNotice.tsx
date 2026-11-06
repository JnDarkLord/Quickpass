import { CalendarOff } from "lucide-react"
import { useSchool } from "@/context/SchoolContext"

const NOTICES = { holiday: "common.holiday_notice", closed: "common.closed_notice" } as const

/** Why a Day View counts nobody absent on a holiday or a weekday without classes; nothing on a School Day. */
export function NoClassesNotice({ date }: { date: string }) {
  const { t, formatDate, dayKind } = useSchool()
  const kind = dayKind(date)
  if (kind === "school_day") {
    return null
  }
  return (
    <p
      role="status"
      className="flex items-center rounded-lg border border-violet-200 bg-violet-50 px-4 py-3 text-sm font-medium text-violet-800"
    >
      <CalendarOff className="h-4 w-4 mr-2 shrink-0" />
      {t(NOTICES[kind], { date: formatDate(date) })}
    </p>
  )
}
