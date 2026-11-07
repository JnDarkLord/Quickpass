import { Badge, type BadgeProps } from "@/components/ui/badge"
import { useSchool } from "@/context/SchoolContext"
import { isDayStatus, STATUS_LABELS, type DayStatus } from "@/lib/status"

const VARIANTS = {
  on_time: "success",
  late: "warning",
  departed: "info",
  absent: "destructive",
  no_classes: "outline",
} as const satisfies Record<DayStatus, BadgeProps["variant"]>

export function StatusBadge({ status }: { status: string }) {
  const { t } = useSchool()
  if (!isDayStatus(status)) {
    return <Badge variant="outline">{status}</Badge>
  }
  return <Badge variant={VARIANTS[status]}>{t(STATUS_LABELS[status])}</Badge>
}
