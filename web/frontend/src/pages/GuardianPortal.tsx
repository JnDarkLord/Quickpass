import { useEffect, useState } from "react"
import { useAuth } from "@/context/AuthContext"
import { useSchool, type DayKind } from "@/context/SchoolContext"
import type { MessageKey } from "@/lib/i18n"
import { getPortalBackend } from "@/lib/supabase"
import { localToday } from "@/lib/utils"
import { Navbar } from "@/components/Navbar"
import { NoClassesNotice } from "@/components/NoClassesNotice"
import { StatusBadge } from "@/components/StatusBadge"
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import {
  Calendar as CalendarIcon,
  CheckCircle2,
  Clock,
  DoorOpen,
  UserCheck,
  UserX,
  AlertTriangle,
  RefreshCw,
  ChevronLeft,
  ChevronRight,
} from "lucide-react"

const WEEKDAYS = ["sun", "mon", "tue", "wed", "thu", "fri", "sat"] as const

interface DayStyle {
  label: MessageKey | null
  cell: string
  /** The legend's color sample. */
  dot?: string
}

/** The Year View's day marks: P for on time, T for late, A for absent. */
const MARKS = {
  P: { mark: "mark.present", label: "guardian.calendar.on_time", cell: "bg-emerald-50 border-emerald-200 text-emerald-900", badge: "bg-emerald-600", dot: "bg-emerald-500" },
  T: { mark: "mark.late", label: "guardian.calendar.late", cell: "bg-amber-50 border-amber-200 text-amber-900", badge: "bg-amber-600", dot: "bg-amber-500" },
  A: { mark: "mark.absent", label: "guardian.calendar.absent", cell: "bg-rose-50 border-rose-200 text-rose-900", badge: "bg-rose-600", dot: "bg-rose-500" },
} as const satisfies Record<string, DayStyle & { mark: MessageKey; badge: string }>

const DAYS_WITHOUT_MARK = {
  school_day: { label: null, cell: "bg-white border border-slate-200" },
  holiday: { label: "guardian.calendar.holiday", cell: "bg-violet-50 border border-dashed border-violet-300 text-violet-700", dot: "bg-violet-300" },
  closed: { label: "guardian.calendar.no_classes", cell: "bg-slate-100 border border-slate-100 text-slate-400", dot: "bg-slate-300" },
} as const satisfies Record<DayKind, DayStyle>

export function GuardianPortal() {
  const { user } = useAuth()
  const { t, formatDate, formatTime, formatMonth, gradeLabel, dayKind, lateThreshold } = useSchool()
  const [activeView, setActiveView] = useState<"day" | "year">("day")
  const [dayData, setDayData] = useState<any>(null)
  const [yearData, setYearData] = useState<any>(null)
  const [loading, setLoading] = useState(true)
  const [refreshing, setRefreshing] = useState(false)
  const [selectedChildIndex, setSelectedChildIndex] = useState(0)
  const [calendarMonth, setCalendarMonth] = useState(new Date())

  const [adminFamilyId, setAdminFamilyId] = useState<string>("FAM-0001")
  const [adminFamilyInput, setAdminFamilyInput] = useState<string>("FAM-0001")

  const effectiveFamilyId = user?.role === "admin" ? adminFamilyId : user?.linked_entity_id

  const handleFamilySubmit = (e?: React.FormEvent) => {
    if (e) e.preventDefault()
    const trimmed = adminFamilyInput.trim().toUpperCase()
    if (!trimmed) return
    const normalized = /^\d+$/.test(trimmed)
      ? `FAM-${trimmed.padStart(4, "0")}`
      : trimmed.startsWith("FAM-")
      ? trimmed
      : `FAM-${trimmed}`
    setAdminFamilyId(normalized)
    setAdminFamilyInput(normalized)
    setSelectedChildIndex(0)
  }

  const prevMonth = () => {
    setCalendarMonth(new Date(calendarMonth.getFullYear(), calendarMonth.getMonth() - 1, 1))
  }
  const nextMonth = () => {
    setCalendarMonth(new Date(calendarMonth.getFullYear(), calendarMonth.getMonth() + 1, 1))
  }

  const fetchDayView = async () => {
    try {
      const date = localToday()
      const data = await getPortalBackend().fetchDayView({
        date,
        schoolDay: dayKind(date) === "school_day",
        familyId: effectiveFamilyId,
      })
      setDayData(data)
    } catch (err) {
      console.error("Error fetching guardian day attendance:", err)
    }
  }

  const fetchYearView = async () => {
    try {
      const data = await getPortalBackend().fetchYearView()
      if (user?.role === "admin" && data?.students) {
        const filtered = data.students.filter((st: any) => st.family_id === effectiveFamilyId)
        setYearData({
          ...data,
          family_id: effectiveFamilyId,
          total_students: filtered.length,
          students: filtered,
        })
      } else {
        setYearData(data)
      }
    } catch (err) {
      console.error("Error fetching guardian year attendance:", err)
    }
  }

  const loadData = async () => {
    setLoading(true)
    await Promise.all([fetchDayView(), fetchYearView()])
    setLoading(false)
  }

  useEffect(() => {
    loadData()
  }, [effectiveFamilyId])

  const handleRefresh = async () => {
    setRefreshing(true)
    if (activeView === "day") {
      await fetchDayView()
    } else {
      await fetchYearView()
    }
    setRefreshing(false)
  }

  const currentChild = yearData?.students?.[selectedChildIndex] || null

  return (
    <div className="min-h-screen bg-slate-50 flex flex-col">
      <Navbar activeView={activeView} onViewChange={setActiveView} />

      <main className="flex-1 max-w-7xl w-full mx-auto p-4 sm:p-6 lg:p-8 space-y-6">
        {/* Subheader with Family & Actions */}
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 bg-white p-4 sm:p-6 rounded-xl border border-slate-200 shadow-sm">
          <div>
            <div className="flex items-center space-x-2">
              <h2 className="text-xl sm:text-2xl font-bold text-slate-900">
                {t("guardian.family_title", { name: (user?.role === "admin" ? effectiveFamilyId : user?.name) ?? "" })}
              </h2>
              <Badge variant="info" className="text-xs">
                {effectiveFamilyId}
              </Badge>
              {user?.role === "admin" && (
                <Badge variant="outline" className="border-purple-300 text-purple-700 bg-purple-50 text-xs">
                  {t("guardian.admin_simulation")}
                </Badge>
              )}
            </div>
            <p className="text-sm text-slate-500 mt-1">
              {t("guardian.subtitle")}
            </p>
          </div>

          <div className="flex flex-wrap items-center gap-3">
            {user?.role === "admin" && (
              <form
                onSubmit={handleFamilySubmit}
                className="flex items-center space-x-2 bg-purple-50 border border-purple-200 px-3 py-1.5 rounded-lg text-xs"
              >
                <span className="font-semibold text-purple-900 shrink-0">
                  {t("guardian.family_code_label")}
                </span>
                <Input
                  aria-label={t("guardian.family_code_input")}
                  value={adminFamilyInput}
                  onChange={(e) => setAdminFamilyInput(e.target.value)}
                  onBlur={() => handleFamilySubmit()}
                  placeholder="FAM-0001, 9999..."
                  className="h-7 w-28 sm:w-36 text-xs bg-white font-mono uppercase border-purple-300 focus-visible:ring-purple-500"
                />
                <Button
                  type="submit"
                  size="sm"
                  className="h-7 px-2.5 text-xs bg-purple-700 hover:bg-purple-800 text-white font-medium"
                >
                  {t("common.search")}
                </Button>
              </form>
            )}

            <Button
              variant="outline"
              size="sm"
              onClick={handleRefresh}
              disabled={refreshing}
              className="text-slate-600"
            >
              <RefreshCw className={`h-4 w-4 mr-1.5 ${refreshing ? "animate-spin" : ""}`} />
              {t("common.refresh")}
            </Button>
          </div>
        </div>

        {loading ? (
          <div className="py-20 flex flex-col items-center justify-center space-y-3">
            <div className="h-8 w-8 animate-spin rounded-full border-4 border-blue-600 border-t-transparent" />
            <p className="text-sm text-slate-500 font-medium">{t("guardian.loading")}</p>
          </div>
        ) : activeView === "day" ? (
          /* ================= DAY VIEW ================= */
          <div className="space-y-6">
            {dayData?.date && <NoClassesNotice date={dayData.date} />}

            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
              {(!dayData?.students || dayData.students.length === 0) && (
                <div className="py-16 text-center text-slate-500 bg-white rounded-xl border border-slate-200 p-8 col-span-full">
                  <p className="font-semibold text-slate-700">{t("guardian.day.no_students", { family: effectiveFamilyId ?? "" })}</p>
                  <p className="text-xs text-slate-400 mt-1">{t("guardian.check_family_code")}</p>
                </div>
              )}
              {dayData?.students?.map((child: any) => (
                <Card
                  key={child.student_id}
                  className="border-slate-200 overflow-hidden hover:shadow-md transition-shadow"
                >
                  <div className="bg-gradient-to-r from-blue-600 to-indigo-600 p-4 text-white">
                    <div className="flex items-center justify-between">
                      <span className="text-xs font-semibold uppercase tracking-wider text-blue-100">
                        {t("guardian.day.grade_section", { grade: gradeLabel(child.grade), section: child.section })}
                      </span>
                      <StatusBadge status={child.status} />
                    </div>
                    <h3 className="text-lg font-bold mt-1 text-white">{child.name}</h3>
                    <p className="text-xs text-blue-200 mt-0.5">{t("common.uid", { uid: child.badge_uid })}</p>
                  </div>

                  <CardContent className="p-5 space-y-4">
                    {/* Live Status Details */}
                    <div className="grid grid-cols-2 gap-3 bg-slate-50 p-3 rounded-lg border border-slate-100">
                      <div>
                        <span className="text-[11px] font-medium text-slate-400 block uppercase">{t("guardian.day.check_in")}</span>
                        <div className="flex items-center space-x-1.5 mt-1">
                          <Clock className="h-4 w-4 text-slate-500" />
                          <span className="font-semibold text-slate-900 text-sm">
                            {child.check_in_time ? formatTime(child.check_in_time) : "--:--"}
                          </span>
                        </div>
                      </div>

                      <div>
                        <span className="text-[11px] font-medium text-slate-400 block uppercase">{t("guardian.day.check_out")}</span>
                        <div className="flex items-center space-x-1.5 mt-1">
                          <DoorOpen className="h-4 w-4 text-slate-500" />
                          <span className="font-semibold text-slate-900 text-sm">
                            {child.check_out_time ? formatTime(child.check_out_time) : child.check_in_time ? t("common.in_school") : "--:--"}
                          </span>
                        </div>
                      </div>
                    </div>

                    {/* Status Description Banner */}
                    <div className="text-xs text-slate-600 bg-slate-100/70 p-3 rounded-lg">
                      {child.status === "on_time" && (
                        <p className="flex items-center text-emerald-700 font-medium">
                          <CheckCircle2 className="h-4 w-4 mr-1.5 shrink-0" />
                          {t("guardian.day.on_time_note", { time: formatTime(lateThreshold, { seconds: false }) })}
                        </p>
                      )}
                      {child.status === "late" && (
                        <p className="flex items-center text-amber-700 font-medium">
                          <AlertTriangle className="h-4 w-4 mr-1.5 shrink-0" />
                          {t("guardian.day.late_note")}
                        </p>
                      )}
                      {child.status === "departed" && (
                        <p className="flex items-center text-blue-700 font-medium">
                          <UserCheck className="h-4 w-4 mr-1.5 shrink-0" />
                          {t("guardian.day.departed_note", { time: child.check_out_time ? formatTime(child.check_out_time) : "--:--" })}
                        </p>
                      )}
                      {child.status === "absent" && (
                        <p className="flex items-center text-rose-700 font-medium">
                          <UserX className="h-4 w-4 mr-1.5 shrink-0" />
                          {t("guardian.day.absent_note")}
                        </p>
                      )}
                      {child.status === "no_classes" && (
                        <p className="flex items-center text-violet-700 font-medium">
                          <CalendarIcon className="h-4 w-4 mr-1.5 shrink-0" />
                          {t(dayKind(dayData.date) === "holiday" ? "guardian.calendar.holiday" : "guardian.calendar.no_classes")}
                        </p>
                      )}
                    </div>
                  </CardContent>
                </Card>
              ))}
            </div>
          </div>
        ) : (
          /* ================= YEAR VIEW ================= */
          <div className="space-y-6">
            {/* Multiple children tab toggle */}
            {yearData?.students?.length > 1 && (
              <div className="flex items-center space-x-2 border-b border-slate-200 pb-3">
                <span className="text-xs font-semibold text-slate-400 uppercase tracking-wider mr-2">
                  {t("guardian.year.select_child")}
                </span>
                {yearData.students.map((st: any, idx: number) => (
                  <Button
                    key={st.student_id}
                    variant={selectedChildIndex === idx ? "default" : "outline"}
                    size="sm"
                    onClick={() => setSelectedChildIndex(idx)}
                  >
                    {t("guardian.year.child", { name: st.name, grade: gradeLabel(st.grade), section: st.section })}
                  </Button>
                ))}
              </div>
            )}

            {(!yearData?.students || yearData.students.length === 0) && (
              <div className="py-16 text-center text-slate-500 bg-white rounded-xl border border-slate-200 p-8">
                <p className="font-semibold text-slate-700">{t("guardian.year.no_records", { family: effectiveFamilyId ?? "" })}</p>
                <p className="text-xs text-slate-400 mt-1">{t("guardian.check_family_code")}</p>
              </div>
            )}

            {currentChild && (
              <>
                {/* Year KPI Metric Cards */}
                <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                  <Card className="p-4 border-slate-200">
                    <span className="text-xs font-semibold text-slate-500 uppercase tracking-wider">
                      {t("guardian.year.overall_punctuality")}
                    </span>
                    <p className="text-2xl font-bold text-blue-600 mt-1">
                      {currentChild.metrics?.punctuality_rate}%
                    </p>
                  </Card>

                  <Card className="p-4 border-slate-200">
                    <span className="text-xs font-semibold text-slate-500 uppercase tracking-wider">
                      {t("column.present_days")}
                    </span>
                    <p className="text-2xl font-bold text-emerald-600 mt-1">
                      {currentChild.metrics?.present_days}
                    </p>
                  </Card>

                  <Card className="p-4 border-slate-200">
                    <span className="text-xs font-semibold text-slate-500 uppercase tracking-wider">
                      {t("column.late_days")}
                    </span>
                    <p className="text-2xl font-bold text-amber-600 mt-1">
                      {currentChild.metrics?.late_days}
                    </p>
                  </Card>

                  <Card className="p-4 border-slate-200">
                    <span className="text-xs font-semibold text-slate-500 uppercase tracking-wider">
                      {t("column.absences")}
                    </span>
                    <p className="text-2xl font-bold text-rose-600 mt-1">
                      {currentChild.metrics?.absent_days ?? 0}
                    </p>
                  </Card>
                </div>

                {/* Interactive Monthly Attendance Calendar */}
                <Card className="border-slate-200">
                  <CardHeader className="flex flex-row items-center justify-between pb-3">
                    <div>
                      <CardTitle className="text-base flex items-center">
                        <CalendarIcon className="h-4 w-4 mr-2 text-indigo-600" />
                        {t("guardian.calendar.title")}
                      </CardTitle>
                      <CardDescription>
                        {t("guardian.calendar.description", { name: currentChild.name })}
                      </CardDescription>
                    </div>
                    <div className="flex items-center space-x-2">
                      <Button variant="outline" size="sm" onClick={prevMonth} className="h-8 w-8 p-0" aria-label={t("guardian.calendar.previous_month")}>
                        <ChevronLeft className="h-4 w-4" />
                      </Button>
                      <span className="text-sm font-semibold text-slate-800 capitalize min-w-28 text-center">
                        {formatMonth(calendarMonth)}
                      </span>
                      <Button variant="outline" size="sm" onClick={nextMonth} className="h-8 w-8 p-0" aria-label={t("guardian.calendar.next_month")}>
                        <ChevronRight className="h-4 w-4" />
                      </Button>
                    </div>
                  </CardHeader>
                  <CardContent>
                    {(() => {
                      const yr = calendarMonth.getFullYear()
                      const mth = calendarMonth.getMonth()
                      const firstDay = new Date(yr, mth, 1).getDay()
                      const totalDays = new Date(yr, mth + 1, 0).getDate()
                      const historyMap: Record<string, any> = {}
                      currentChild.history?.forEach((h: any) => {
                        historyMap[h.date] = h
                      })

                      const markOf = (dateKey: string): keyof typeof MARKS | null => {
                        const record = historyMap[dateKey]
                        const dayMark = currentChild.days?.[dateKey]
                        if (dayMark === "T" || record?.checkin_status === "late" || record?.status === "late") return "T"
                        if (dayMark === "P" || record?.checkin_status === "on_time" || record?.status === "on_time" || record?.status === "departed") return "P"
                        if (dayMark === "A" || record?.status === "absent") return "A"
                        return null
                      }

                      return (
                        <>
                          <div className="grid grid-cols-7 gap-1 text-center font-semibold text-xs text-slate-500 mb-2">
                            {WEEKDAYS.map((weekday) => (
                              <span key={weekday}>{t(`guardian.calendar.weekday.${weekday}`)}</span>
                            ))}
                          </div>
                          <div className="grid grid-cols-7 gap-1">
                            {Array.from({ length: firstDay }).map((_, idx) => (
                              <div key={`empty-${idx}`} className="h-12 bg-slate-50/50 rounded-md" />
                            ))}
                            {Array.from({ length: totalDays }).map((_, idx) => {
                              const dayNum = idx + 1
                              const dayStr = String(dayNum).padStart(2, "0")
                              const mStr = String(mth + 1).padStart(2, "0")
                              const dateKey = `${yr}-${mStr}-${dayStr}`
                              const mark = markOf(dateKey)
                              const style = mark ? MARKS[mark] : DAYS_WITHOUT_MARK[dayKind(dateKey)]

                              return (
                                <div
                                  key={dateKey}
                                  title={style.label ? t(style.label) : undefined}
                                  className={`h-12 p-1 rounded-md flex flex-col justify-between items-center transition-all ${style.cell}`}
                                >
                                  <span className="text-xs font-medium">{dayNum}</span>
                                  {mark && (
                                    <span className={`text-[10px] font-bold px-1.5 py-0.5 rounded text-white ${MARKS[mark].badge}`}>
                                      {t(MARKS[mark].mark)}
                                    </span>
                                  )}
                                </div>
                              )
                            })}
                          </div>
                          <div className="mt-4 pt-3 border-t border-slate-100 flex flex-wrap items-center justify-center gap-4 text-xs text-slate-600">
                            {(Object.keys(MARKS) as Array<keyof typeof MARKS>).map((code) => (
                              <span key={code} className="flex items-center">
                                <span className={`w-2.5 h-2.5 rounded-full mr-1.5 ${MARKS[code].dot}`}></span>
                                <strong>{t(MARKS[code].mark)}</strong> = {t(MARKS[code].label)}
                              </span>
                            ))}
                            <span className="flex items-center">
                              <span className={`w-2.5 h-2.5 rounded-full mr-1.5 ${DAYS_WITHOUT_MARK.holiday.dot}`}></span>
                              {t("guardian.calendar.holiday")}
                            </span>
                            <span className="flex items-center">
                              <span className={`w-2.5 h-2.5 rounded-full mr-1.5 ${DAYS_WITHOUT_MARK.closed.dot}`}></span>
                              {t("guardian.calendar.no_classes")}
                            </span>
                          </div>
                        </>
                      )
                    })()}
                  </CardContent>
                </Card>

                {/* Detailed Attendance Table */}
                <Card className="border-slate-200">
                  <CardHeader>
                    <CardTitle className="text-base flex items-center">
                      <CalendarIcon className="h-4 w-4 mr-2 text-blue-600" />
                      {t("guardian.history.title", { name: currentChild.name })}
                    </CardTitle>
                    <CardDescription>
                      {t("guardian.history.description")}
                    </CardDescription>
                  </CardHeader>

                  <CardContent>
                    {currentChild.history?.length === 0 ? (
                      <p className="py-8 text-center text-sm text-slate-500">
                        {t("guardian.history.empty")}
                      </p>
                    ) : (
                      <Table>
                        <TableHeader>
                          <TableRow>
                            <TableHead>{t("column.date")}</TableHead>
                            <TableHead>{t("column.check_in_time")}</TableHead>
                            <TableHead>{t("column.check_out_time")}</TableHead>
                            <TableHead>{t("column.status")}</TableHead>
                          </TableRow>
                        </TableHeader>
                        <TableBody>
                          {currentChild.history.map((row: any, idx: number) => (
                            <TableRow key={idx}>
                              <TableCell className="font-medium text-slate-900">{formatDate(row.date)}</TableCell>
                              <TableCell>{row.check_in_time ? formatTime(row.check_in_time) : "--:--"}</TableCell>
                              <TableCell>{row.check_out_time ? formatTime(row.check_out_time) : "--:--"}</TableCell>
                              <TableCell><StatusBadge status={row.status} /></TableCell>
                            </TableRow>
                          ))}
                        </TableBody>
                      </Table>
                    )}
                  </CardContent>
                </Card>
              </>
            )}
          </div>
        )}
      </main>
    </div>
  )
}
