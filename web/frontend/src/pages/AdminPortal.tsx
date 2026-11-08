import { useEffect, useState } from "react"
import { ALL, getPortalBackend } from "@/lib/supabase"
import { useSchool } from "@/context/SchoolContext"
import { isDayStatus, STATUS_LABELS } from "@/lib/status"
import { localToday, safeFileName } from "@/lib/utils"
import { Navbar } from "@/components/Navbar"
import { NoClassesNotice } from "@/components/NoClassesNotice"
import { StatusBadge } from "@/components/StatusBadge"
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { exportRows, type SpreadsheetFormat, type SpreadsheetRow } from "@/lib/spreadsheet"
import {
  Calendar,
  Clock,
  Download,
  RefreshCw,
  Search,
  ShieldCheck,
  TrendingUp,
} from "lucide-react"

export function AdminPortal() {
  const { t, formatDate, formatTime, gradeLabel, grades, sections, dayKind } = useSchool()
  const [activeView, setActiveView] = useState<"day" | "year">("day")

  // Universal Filter State
  const [selectedDate, setSelectedDate] = useState(localToday)
  const [selectedGrade, setSelectedGrade] = useState<string>(ALL)
  const [selectedSection, setSelectedSection] = useState<string>(ALL)
  const [searchQuery, setSearchQuery] = useState("")

  // Year View Date Range
  const [startDate, setStartDate] = useState("2026-01-01")
  const [endDate, setEndDate] = useState(localToday)

  const [dayData, setDayData] = useState<any>(null)
  const [yearData, setYearData] = useState<any>(null)
  const [loading, setLoading] = useState(true)
  const [refreshing, setRefreshing] = useState(false)

  const fetchDayView = async () => {
    try {
      const date = selectedDate || localToday()
      const data = await getPortalBackend().fetchDayView({
        date,
        schoolDay: dayKind(date) === "school_day",
        grade: selectedGrade !== ALL ? Number(selectedGrade) : undefined,
        section: selectedSection !== ALL ? selectedSection : undefined,
        search: searchQuery.trim() || undefined,
      })
      setDayData(data)
    } catch (err) {
      console.error("Error fetching admin day attendance:", err)
    }
  }

  const fetchYearView = async () => {
    try {
      const data = await getPortalBackend().fetchYearView({
        grade: selectedGrade !== ALL ? Number(selectedGrade) : undefined,
        section: selectedSection !== ALL ? selectedSection : undefined,
        startDate: startDate || undefined,
        endDate: endDate || undefined,
        search: searchQuery.trim() || undefined,
      })
      setYearData(data)
    } catch (err) {
      console.error("Error fetching admin year attendance:", err)
    }
  }

  const loadData = async () => {
    setLoading(true)
    await Promise.all([fetchDayView(), fetchYearView()])
    setLoading(false)
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
  }, [selectedDate, selectedGrade, selectedSection, searchQuery, startDate, endDate, activeView])

  const handleRefresh = async () => {
    setRefreshing(true)
    if (activeView === "day") {
      await fetchDayView()
    } else {
      await fetchYearView()
    }
    setRefreshing(false)
  }

  const statusText = (status: string) => (isDayStatus(status) ? t(STATUS_LABELS[status]) : status)

  const handleExport = async (format: SpreadsheetFormat = "xlsx") => {
    const studentsToExport = activeView === "day" ? dayData?.students : yearData?.students
    if (!studentsToExport || studentsToExport.length === 0) {
      alert(t("admin.export_empty"))
      return
    }

    let worksheetData: SpreadsheetRow[] = []

    if (activeView === "day") {
      worksheetData = studentsToExport.map((s: any) => ({
        [t("export.student_id")]: s.student_id,
        [t("export.full_name")]: s.name,
        [t("export.badge_uid")]: s.badge_uid,
        [t("export.grade")]: gradeLabel(s.grade),
        [t("column.section")]: s.section,
        [t("column.family_code")]: s.family_id,
        [t("column.check_in_time")]: s.check_in_time ? formatTime(s.check_in_time) : "--",
        [t("column.check_out_time")]: s.check_out_time ? formatTime(s.check_out_time) : "--",
        [t("column.status")]: statusText(s.status),
      }))
    } else {
      worksheetData = studentsToExport.map((s: any) => ({
        [t("export.student_id")]: s.student_id,
        [t("export.full_name")]: s.name,
        [t("column.family_code")]: s.family_id || "--",
        [t("export.grade")]: gradeLabel(s.grade),
        [t("column.section")]: s.section,
        [t("column.present_days")]: s.present_days,
        [t("column.late_days")]: s.late_days,
        [t("column.absences")]: s.absent_days ?? 0,
        [t("export.punctuality_percent")]: s.punctuality_rate,
      }))
    }

    const name = activeView === "day"
      ? t("admin.day.export_file", { date: formatDate(dayData?.date ?? selectedDate) })
      : t("admin.year.export_file", { start: formatDate(startDate), end: formatDate(endDate) })
    const filename = safeFileName(`${name}.${format}`)

    await exportRows(worksheetData, {
      sheetName: activeView === "day" ? t("admin.day.export_sheet") : t("admin.year.export_sheet"),
      fileName: filename,
      format,
    })
  }

  return (
    <div className="min-h-screen bg-slate-50 flex flex-col">
      <Navbar activeView={activeView} onViewChange={setActiveView} />

      <main className="flex-1 max-w-7xl w-full mx-auto p-4 sm:p-6 lg:p-8 space-y-6">
        {/* Universal Filter Bar */}
        <div className="bg-white p-5 rounded-xl border border-slate-200 shadow-sm space-y-4">
          <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
            <div className="flex items-center space-x-2">
              <ShieldCheck className="h-6 w-6 text-purple-600" />
              <div>
                <h2 className="text-xl font-bold text-slate-900">{t("admin.title")}</h2>
                <p className="text-xs text-slate-500">
                  {t("admin.subtitle")}
                </p>
              </div>
            </div>

            <div className="flex items-center space-x-2">
              <Button
                variant="outline"
                size="sm"
                onClick={() => handleExport("xlsx")}
                className="text-slate-700 font-medium"
              >
                <Download className="h-4 w-4 mr-1.5 text-emerald-600" />
                Excel (.xlsx)
              </Button>
              <Button
                variant="outline"
                size="sm"
                onClick={() => handleExport("csv")}
                className="text-slate-700 font-medium"
              >
                <Download className="h-4 w-4 mr-1.5 text-blue-600" />
                CSV
              </Button>
              <Button
                variant="outline"
                size="sm"
                onClick={handleRefresh}
                disabled={refreshing}
                className="text-slate-700"
              >
                <RefreshCw className={`h-4 w-4 mr-1.5 ${refreshing ? "animate-spin" : ""}`} />
                {t("common.refresh")}
              </Button>
            </div>
          </div>

          {/* Filter Controls Row */}
          <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-4 gap-3 pt-2 border-t border-slate-100">
            {activeView === "day" ? (
              <div>
                <label htmlFor="admin-date" className="text-[11px] font-semibold text-slate-400 uppercase tracking-wider block mb-1">
                  {t("admin.filter.date")}
                </label>
                <Input
                  id="admin-date"
                  type="date"
                  value={selectedDate}
                  onChange={(e) => setSelectedDate(e.target.value)}
                  className="h-9 text-sm"
                />
              </div>
            ) : (
              <div className="grid grid-cols-2 gap-2">
                <div>
                  <label htmlFor="admin-from" className="text-[11px] font-semibold text-slate-400 uppercase tracking-wider block mb-1">
                    {t("admin.filter.from")}
                  </label>
                  <Input
                    id="admin-from"
                    type="date"
                    value={startDate}
                    onChange={(e) => setStartDate(e.target.value)}
                    className="h-9 text-xs"
                  />
                </div>
                <div>
                  <label htmlFor="admin-to" className="text-[11px] font-semibold text-slate-400 uppercase tracking-wider block mb-1">
                    {t("admin.filter.to")}
                  </label>
                  <Input
                    id="admin-to"
                    type="date"
                    value={endDate}
                    onChange={(e) => setEndDate(e.target.value)}
                    className="h-9 text-xs"
                  />
                </div>
              </div>
            )}

            <div>
              <label htmlFor="admin-grade" className="text-[11px] font-semibold text-slate-400 uppercase tracking-wider block mb-1">
                {t("admin.filter.grade")}
              </label>
              <select
                id="admin-grade"
                value={selectedGrade}
                onChange={(e) => setSelectedGrade(e.target.value)}
                className="h-9 w-full rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-sm text-slate-900 shadow-sm focus:outline-none focus:ring-2 focus:ring-purple-500"
              >
                <option value={ALL}>{t("admin.filter.all_grades")}</option>
                {grades.map((label, index) => (
                  <option key={label} value={index + 1}>
                    {label}
                  </option>
                ))}
              </select>
            </div>

            <div>
              <label htmlFor="admin-section" className="text-[11px] font-semibold text-slate-400 uppercase tracking-wider block mb-1">
                {t("admin.filter.section")}
              </label>
              <select
                id="admin-section"
                value={selectedSection}
                onChange={(e) => setSelectedSection(e.target.value)}
                className="h-9 w-full rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-sm text-slate-900 shadow-sm focus:outline-none focus:ring-2 focus:ring-purple-500"
              >
                <option value={ALL}>{t("admin.filter.all_sections")}</option>
                {sections.map((section) => (
                  <option key={section} value={section}>
                    {t("common.section", { section })}
                  </option>
                ))}
              </select>
            </div>

            <div>
              <label htmlFor="admin-search" className="text-[11px] font-semibold text-slate-400 uppercase tracking-wider block mb-1">
                {t("admin.filter.search")}
              </label>
              <div className="relative">
                <Search className="absolute left-2.5 top-2.5 h-4 w-4 text-slate-400" />
                <Input
                  id="admin-search"
                  placeholder={t("admin.filter.search_placeholder")}
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  className="pl-8 h-9 text-sm"
                />
              </div>
            </div>
          </div>
        </div>

        {/* View Body */}
        {loading ? (
          <div className="py-20 flex flex-col items-center justify-center space-y-3">
            <div className="h-8 w-8 animate-spin rounded-full border-4 border-purple-600 border-t-transparent" />
            <p className="text-sm text-slate-500 font-medium">{t("admin.loading")}</p>
          </div>
        ) : activeView === "day" ? (
          /* ================= DAY VIEW ================= */
          <div className="space-y-6">
            {dayData?.date && <NoClassesNotice date={dayData.date} />}

            {/* KPI Metric Counters */}
            <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-5 gap-4">
              <Card className="p-4 border-slate-200">
                <span className="text-xs font-semibold text-slate-400 uppercase tracking-wider">
                  {t("admin.day.total_enrolled")}
                </span>
                <p className="text-2xl font-bold text-slate-900 mt-1">
                  {dayData?.summary?.total_enrolled || 0}
                </p>
              </Card>

              <Card className="p-4 border-slate-200">
                <span className="text-xs font-semibold text-slate-400 uppercase tracking-wider">
                  {t("admin.day.present")}
                </span>
                <p className="text-2xl font-bold text-emerald-600 mt-1">
                  {dayData?.summary?.present_today || 0}
                </p>
              </Card>

              <Card className="p-4 border-slate-200">
                <span className="text-xs font-semibold text-slate-400 uppercase tracking-wider">
                  {t("admin.day.late")}
                </span>
                <p className="text-2xl font-bold text-amber-600 mt-1">
                  {dayData?.summary?.late_today || 0}
                </p>
              </Card>

              <Card className="p-4 border-slate-200">
                <span className="text-xs font-semibold text-slate-400 uppercase tracking-wider">
                  {t("admin.day.absences")}
                </span>
                <p className="text-2xl font-bold text-rose-600 mt-1">
                  {dayData?.summary?.absent_today || 0}
                </p>
              </Card>

              <Card className="p-4 border-slate-200 col-span-2 sm:col-span-1">
                <span className="text-xs font-semibold text-slate-400 uppercase tracking-wider flex items-center">
                  <TrendingUp className="h-3 w-3 mr-1 text-purple-600" /> {t("admin.day.attendance_rate")}
                </span>
                <p className="text-2xl font-bold text-purple-600 mt-1">
                  {dayData?.summary?.attendance_rate == null ? "--" : `${dayData.summary.attendance_rate}%`}
                </p>
              </Card>
            </div>

            {/* Live Feed Table */}
            <Card className="border-slate-200">
              <CardHeader className="pb-3">
                <CardTitle className="text-base flex items-center">
                  <Clock className="h-4 w-4 mr-2 text-purple-600" />
                  {t("admin.day.feed_title", { date: formatDate(dayData?.date ?? selectedDate) })}
                </CardTitle>
                <CardDescription>
                  {t("admin.day.feed_description")}
                </CardDescription>
              </CardHeader>

              <CardContent>
                {dayData?.students?.length === 0 ? (
                  <div className="py-12 text-center text-slate-400 text-sm">
                    {t("admin.day.empty")}
                  </div>
                ) : (
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead>{t("column.student")}</TableHead>
                        <TableHead>{t("column.grade_section")}</TableHead>
                        <TableHead>{t("column.family_code")}</TableHead>
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
                            <Badge variant="outline">
                              {t("common.grade_section", { grade: gradeLabel(s.grade), section: s.section })}
                            </Badge>
                          </TableCell>
                          <TableCell className="font-mono text-xs text-slate-500">
                            {s.family_id}
                          </TableCell>
                          <TableCell className="font-mono text-sm">
                            {s.check_in_time ? formatTime(s.check_in_time) : "--:--"}
                          </TableCell>
                          <TableCell className="font-mono text-sm">
                            {s.check_out_time ? formatTime(s.check_out_time) : s.check_in_time ? t("common.in_school") : "--:--"}
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
            <Card className="border-slate-200">
              <CardHeader className="pb-3">
                <CardTitle className="text-base flex items-center">
                  <Calendar className="h-4 w-4 mr-2 text-purple-600" />
                  {t("admin.year.title", { start: formatDate(startDate), end: formatDate(endDate) })}
                </CardTitle>
                <CardDescription>
                  {t("admin.year.description")}
                </CardDescription>
              </CardHeader>

              <CardContent>
                {yearData?.students?.length === 0 ? (
                  <div className="py-12 text-center text-slate-400 text-sm">
                    {t("admin.year.empty")}
                  </div>
                ) : (
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead>{t("column.student")}</TableHead>
                        <TableHead>{t("column.family_code")}</TableHead>
                        <TableHead>{t("column.grade_section")}</TableHead>
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
                            {st.badge_uid && (
                              <span className="block text-[11px] text-slate-400 font-normal">
                                {t("common.uid", { uid: st.badge_uid })}
                              </span>
                            )}
                          </TableCell>
                          <TableCell className="font-mono text-xs text-slate-500">
                            {st.family_id || "--"}
                          </TableCell>
                          <TableCell>
                            <Badge variant="outline">
                              {t("common.grade_section", { grade: gradeLabel(st.grade), section: st.section })}
                            </Badge>
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
