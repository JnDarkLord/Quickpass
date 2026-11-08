import { useEffect, useState } from "react"
import { useAuth } from "@/context/AuthContext"
import { useSchool } from "@/context/SchoolContext"
import type { MessageKey } from "@/lib/i18n"
import { localToday, safeFileName } from "@/lib/utils"
import { ALL, getPortalBackend } from "@/lib/supabase"
import { Navbar } from "@/components/Navbar"
import { NoClassesNotice } from "@/components/NoClassesNotice"
import { StatusBadge } from "@/components/StatusBadge"
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import {
  Calendar,
  Filter,
  GraduationCap,
  RefreshCw,
  Search,
  Download,
  Printer,
} from "lucide-react"
import { exportRows } from "@/lib/spreadsheet"

const MARK_KEYS = { P: "mark.present", T: "mark.late", A: "mark.absent" } as const satisfies Record<string, MessageKey>

export function TeacherPortal() {
  const { user } = useAuth()
  const { t, formatDate, formatShortDate, formatTime, gradeLabel, grades, sections, dayKind } = useSchool()
  const [activeView, setActiveView] = useState<"day" | "year">("day")
  const [sectionFilter, setSectionFilter] = useState(ALL)
  const [searchQuery, setSearchQuery] = useState("")
  const [startDate, setStartDate] = useState("")
  const [endDate, setEndDate] = useState("")
  const [adminGrade, setAdminGrade] = useState<number>(1)
  const [dayData, setDayData] = useState<any>(null)
  const [yearData, setYearData] = useState<any>(null)
  const [loading, setLoading] = useState(true)
  const [refreshing, setRefreshing] = useState(false)

  const taughtGrade =
    user?.role === "admin"
      ? adminGrade
      : user?.details?.taught_grade
      ? Number(user.details.taught_grade)
      : 1

  const fetchDayView = async () => {
    try {
      const date = localToday()
      const data = await getPortalBackend().fetchDayView({
        date,
        schoolDay: dayKind(date) === "school_day",
        grade: taughtGrade,
        section: sectionFilter !== ALL ? sectionFilter : undefined,
        search: searchQuery.trim() || undefined,
      })
      setDayData(data)
    } catch (err) {
      console.error("Error loading teacher day data:", err)
    }
  }

  const fetchYearView = async () => {
    try {
      const data = await getPortalBackend().fetchYearView({
        grade: taughtGrade,
        section: sectionFilter !== ALL ? sectionFilter : undefined,
        startDate: startDate || undefined,
        endDate: endDate || undefined,
      })
      setYearData(data)
    } catch (err) {
      console.error("Error loading teacher year data:", err)
    }
  }

  const loadData = async () => {
    setLoading(true)
    await Promise.all([fetchDayView(), fetchYearView()])
    setLoading(false)
  }

  const handleExportMatrix = async () => {
    if (!yearData?.students || yearData.students.length === 0) {
      alert(t("teacher.year.export_empty"))
      return
    }

    const data = yearData.students.map((st: any) => ({
      [t("column.student")]: st.name,
      [t("export.grade")]: gradeLabel(st.grade ?? taughtGrade),
      [t("column.section")]: st.section,
      [t("column.present_days")]: st.present_days,
      [t("column.late_days")]: st.late_days,
      [t("column.absences")]: st.absent_days ?? 0,
      [t("export.punctuality_percent")]: st.punctuality_rate,
    }))

    await exportRows(data, {
      sheetName: t("teacher.year.export_sheet"),
      fileName: safeFileName(`${t("teacher.year.export_file", { grade: gradeLabel(taughtGrade) })}.xlsx`),
      format: "xlsx",
    })
  }

  useEffect(() => {
    loadData()
  }, [])

  useEffect(() => {
    if (activeView === "day") {
      fetchDayView()
    } else {
      fetchYearView()
    }
  }, [taughtGrade, sectionFilter, searchQuery, startDate, endDate, activeView])

  const handleRefresh = async () => {
    setRefreshing(true)
    if (activeView === "day") {
      await fetchDayView()
    } else {
      await fetchYearView()
    }
    setRefreshing(false)
  }

  return (
    <div className="min-h-screen bg-slate-50 flex flex-col">
      <Navbar activeView={activeView} onViewChange={setActiveView} />

      <main className="flex-1 max-w-7xl w-full mx-auto p-4 sm:p-6 lg:p-8 space-y-6">
        {/* Header Banner */}
        <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 bg-white p-5 rounded-xl border border-slate-200 shadow-sm">
          <div className="flex items-center space-x-3">
            <div className="h-12 w-12 rounded-xl bg-emerald-100 text-emerald-800 flex items-center justify-center font-bold text-xl">
              <GraduationCap className="h-6 w-6 text-emerald-600" />
            </div>
            <div>
              <div className="flex items-center space-x-2">
                <h2 className="text-xl font-bold text-slate-900">{user?.name}</h2>
                <Badge variant={user?.role === "admin" ? "outline" : "success"} className={user?.role === "admin" ? "border-purple-300 text-purple-700 bg-purple-50" : ""}>
                  {user?.role === "admin"
                    ? t("teacher.simulating", { grade: gradeLabel(taughtGrade) })
                    : t("teacher.assigned_grade", { grade: gradeLabel(taughtGrade) })}
                </Badge>
              </div>
              <p className="text-xs text-slate-500 mt-0.5">
                {t("teacher.subtitle")}
              </p>
            </div>
          </div>

          <div className="flex flex-wrap items-center gap-2">
            {/* Admin Grade Switcher */}
            {user?.role === "admin" && (
              <div className="flex items-center space-x-1.5 bg-purple-50 border border-purple-200 px-2.5 py-1 rounded-lg text-xs font-medium">
                <span className="text-purple-700 font-semibold">{t("teacher.grade_label")}</span>
                <select
                  aria-label={t("teacher.grade_select")}
                  value={adminGrade}
                  onChange={(e) => setAdminGrade(Number(e.target.value))}
                  className="bg-white border border-purple-300 text-purple-900 rounded px-2 py-0.5 text-xs font-semibold focus:outline-none"
                >
                  {grades.map((label, index) => (
                    <option key={label} value={index + 1}>
                      {label}
                    </option>
                  ))}
                </select>
              </div>
            )}

            {/* Section filter selector */}
            <div className="flex items-center space-x-1.5 bg-slate-100 p-1 rounded-lg text-xs font-medium">
              <span className="text-slate-400 px-2 flex items-center">
                <Filter className="h-3 w-3 mr-1" /> {t("teacher.section_label")}
              </span>
              {[ALL, ...sections].map((sec) => (
                <button
                  key={sec}
                  type="button"
                  onClick={() => setSectionFilter(sec)}
                  className={`px-2.5 py-1 rounded-md transition-all ${
                    sectionFilter === sec
                      ? "bg-white text-slate-900 shadow-sm font-semibold"
                      : "text-slate-600 hover:text-slate-900"
                  }`}
                >
                  {sec === ALL ? t("teacher.all_sections") : sec}
                </button>
              ))}
            </div>

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

        {/* View Content */}
        {loading ? (
          <div className="py-20 flex flex-col items-center justify-center space-y-3">
            <div className="h-8 w-8 animate-spin rounded-full border-4 border-emerald-600 border-t-transparent" />
            <p className="text-sm text-slate-500 font-medium">{t("teacher.loading")}</p>
          </div>
        ) : activeView === "day" ? (
          /* ================= DAY VIEW ================= */
          <div className="space-y-6">
            {dayData?.date && <NoClassesNotice date={dayData.date} />}

            {/* KPI Metric Counters */}
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
              <Card className="p-4 border-slate-200">
                <span className="text-xs font-semibold text-slate-400 uppercase tracking-wider">
                  {t("teacher.day.enrolled")}
                </span>
                <p className="text-2xl font-bold text-slate-900 mt-1">
                  {dayData?.summary?.total_enrolled || 0}
                </p>
              </Card>

              <Card className="p-4 border-slate-200">
                <span className="text-xs font-semibold text-slate-400 uppercase tracking-wider">
                  {t("teacher.day.present")}
                </span>
                <p className="text-2xl font-bold text-emerald-600 mt-1">
                  {dayData?.summary?.present_today || 0}
                </p>
              </Card>

              <Card className="p-4 border-slate-200">
                <span className="text-xs font-semibold text-slate-400 uppercase tracking-wider">
                  {t("teacher.day.late")}
                </span>
                <p className="text-2xl font-bold text-amber-600 mt-1">
                  {dayData?.summary?.late_today || 0}
                </p>
              </Card>

              <Card className="p-4 border-slate-200">
                <span className="text-xs font-semibold text-slate-400 uppercase tracking-wider">
                  {t("teacher.day.absent")}
                </span>
                <p className="text-2xl font-bold text-rose-600 mt-1">
                  {dayData?.summary?.absent_today || 0}
                </p>
              </Card>
            </div>

            {/* Student Roster Table */}
            <Card className="border-slate-200">
              <CardHeader className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 pb-4">
                <div>
                  <CardTitle className="text-base">
                    {t("teacher.day.roster_title", { date: dayData?.date ? formatDate(dayData.date) : "" })}
                  </CardTitle>
                  <CardDescription>
                    {t("teacher.day.roster_description", { grade: gradeLabel(taughtGrade) })}
                  </CardDescription>
                </div>

                <div className="relative w-full sm:w-64">
                  <Search className="absolute left-3 top-2.5 h-4 w-4 text-slate-400" />
                  <Input
                    placeholder={t("teacher.day.search_placeholder")}
                    value={searchQuery}
                    onChange={(e) => setSearchQuery(e.target.value)}
                    className="pl-9 h-9 text-sm"
                  />
                </div>
              </CardHeader>

              <CardContent>
                {dayData?.students?.length === 0 ? (
                  <div className="py-12 text-center text-slate-400 text-sm">
                    {t("teacher.day.empty")}
                  </div>
                ) : (
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead>{t("column.student")}</TableHead>
                        <TableHead>{t("column.section")}</TableHead>
                        <TableHead>{t("column.check_in_time")}</TableHead>
                        <TableHead>{t("column.check_out_time")}</TableHead>
                        <TableHead>{t("column.status")}</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {dayData?.students?.map((s: any) => (
                        <TableRow key={s.student_id}>
                          <TableCell className="font-semibold text-slate-900">
                            {s.name}
                            <span className="block text-[11px] text-slate-400 font-normal">
                              {t("common.uid", { uid: s.badge_uid })}
                            </span>
                          </TableCell>
                          <TableCell>
                            <Badge variant="outline" className="font-mono">
                              {t("common.section", { section: s.section })}
                            </Badge>
                          </TableCell>
                          <TableCell className="font-mono text-sm">
                            {s.check_in_time ? formatTime(s.check_in_time) : "--:--"}
                          </TableCell>
                          <TableCell className="font-mono text-sm">
                            {s.check_out_time ? formatTime(s.check_out_time) : s.check_in_time ? t("teacher.day.in_class") : "--:--"}
                          </TableCell>
                          <TableCell><StatusBadge status={s.status} /></TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                )}
              </CardContent>
            </Card>
          </div>
        ) : (
          /* ================= YEAR VIEW ================= */
          <div className="space-y-6">
            {/* Grade KPI Summary Cards */}
            <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-3">
              <Card className="p-4 border-slate-200">
                <span className="text-xs font-semibold text-slate-400 uppercase tracking-wider">
                  {t("teacher.year.enrollment")}
                </span>
                <p className="text-2xl font-bold text-slate-900 mt-1">
                  {yearData?.summary?.total_students || yearData?.students?.length || 0}
                </p>
              </Card>

              <Card className="p-4 border-slate-200">
                <span className="text-xs font-semibold text-slate-400 uppercase tracking-wider">
                  {t("column.present_days")}
                </span>
                <p className="text-2xl font-bold text-emerald-600 mt-1">
                  {yearData?.summary?.total_present_days || 0}
                </p>
              </Card>

              <Card className="p-4 border-slate-200">
                <span className="text-xs font-semibold text-slate-400 uppercase tracking-wider">
                  {t("column.late_days")}
                </span>
                <p className="text-2xl font-bold text-amber-600 mt-1">
                  {yearData?.summary?.total_late_days || 0}
                </p>
              </Card>

              <Card className="p-4 border-slate-200">
                <span className="text-xs font-semibold text-slate-400 uppercase tracking-wider">
                  {t("teacher.year.total_absences")}
                </span>
                <p className="text-2xl font-bold text-rose-600 mt-1">
                  {yearData?.summary?.total_absent_days || 0}
                </p>
              </Card>

              <Card className="p-4 border-slate-200 col-span-2 sm:col-span-1">
                <span className="text-xs font-semibold text-slate-400 uppercase tracking-wider">
                  {t("teacher.year.average_punctuality")}
                </span>
                <p className="text-2xl font-bold text-indigo-600 mt-1">
                  {yearData?.summary?.average_punctuality || 100}%
                </p>
              </Card>
            </div>

            <Card className="border-slate-200">
              <CardHeader className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 pb-4">
                <div>
                  <CardTitle className="text-base flex items-center">
                    <Calendar className="h-4 w-4 mr-2 text-emerald-600" />
                    {t("teacher.year.matrix_title", { grade: gradeLabel(taughtGrade) })}
                  </CardTitle>
                  <CardDescription>
                    {t("teacher.year.matrix_description")}
                  </CardDescription>
                </div>

                <div className="flex flex-wrap items-center gap-2">
                  <Input
                    type="date"
                    aria-label={t("teacher.year.start_date")}
                    value={startDate}
                    onChange={(e) => setStartDate(e.target.value)}
                    className="h-8 w-36 text-xs"
                  />
                  <Input
                    type="date"
                    aria-label={t("teacher.year.end_date")}
                    value={endDate}
                    onChange={(e) => setEndDate(e.target.value)}
                    className="h-8 w-36 text-xs"
                  />
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={handleExportMatrix}
                    className="text-slate-700 font-medium"
                  >
                    <Download className="h-4 w-4 mr-1.5 text-emerald-600" />
                    {t("teacher.year.export")}
                  </Button>
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => window.print()}
                    className="text-slate-700"
                  >
                    <Printer className="h-4 w-4 mr-1.5 text-slate-500" />
                    {t("teacher.year.print")}
                  </Button>
                </div>
              </CardHeader>

              <CardContent>
                {yearData?.students?.length === 0 ? (
                  <div className="py-12 text-center text-slate-400 text-sm">
                    {t("teacher.year.empty")}
                  </div>
                ) : (
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead>{t("column.student")}</TableHead>
                        <TableHead>{t("column.section")}</TableHead>
                        <TableHead>{t("column.daily_marks")}</TableHead>
                        <TableHead className="text-center">{t("column.present_days")}</TableHead>
                        <TableHead className="text-center">{t("column.late_days")}</TableHead>
                        <TableHead className="text-center">{t("column.absences")}</TableHead>
                        <TableHead className="text-right">{t("column.punctuality")}</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {yearData?.students?.map((st: any) => (
                        <TableRow key={st.student_id}>
                          <TableCell className="font-semibold text-slate-900">
                            {st.name}
                          </TableCell>
                          <TableCell>
                            <Badge variant="outline">{st.section}</Badge>
                          </TableCell>
                          <TableCell>
                            <div className="flex flex-wrap gap-1">
                              {Object.entries<keyof typeof MARK_KEYS>(st.days || {}).map(([dt, mark]) => (
                                <span
                                  key={dt}
                                  title={`${formatDate(dt)}: ${t(MARK_KEYS[mark])}`}
                                  className={`text-[10px] font-bold px-1.5 py-0.5 rounded ${
                                    mark === "P"
                                      ? "bg-emerald-100 text-emerald-800"
                                      : mark === "T"
                                      ? "bg-amber-100 text-amber-800"
                                      : "bg-rose-100 text-rose-800"
                                  }`}
                                >
                                  {formatShortDate(dt)}:{t(MARK_KEYS[mark])}
                                </span>
                              ))}
                            </div>
                          </TableCell>
                          <TableCell className="text-center font-bold text-emerald-700">
                            {st.present_days}
                          </TableCell>
                          <TableCell className="text-center font-bold text-amber-700">
                            {st.late_days}
                          </TableCell>
                          <TableCell className="text-center font-bold text-rose-700">
                            {st.absent_days ?? 0}
                          </TableCell>
                          <TableCell className="text-right">
                            <Badge
                              variant={
                                st.punctuality_rate >= 85
                                  ? "success"
                                  : st.punctuality_rate >= 70
                                  ? "warning"
                                  : "destructive"
                              }
                            >
                              {st.punctuality_rate}%
                            </Badge>
                          </TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                )}
              </CardContent>
            </Card>
          </div>
        )}
      </main>
    </div>
  )
}
