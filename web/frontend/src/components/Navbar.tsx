import { useLocation, useNavigate } from "react-router-dom"
import { useAuth } from "@/context/AuthContext"
import { useSchool } from "@/context/SchoolContext"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { LogOut, Calendar, Clock, ShieldCheck, GraduationCap, Users } from "lucide-react"

interface NavbarProps {
  activeView: "day" | "year"
  onViewChange: (view: "day" | "year") => void
}

export function Navbar({ activeView, onViewChange }: NavbarProps) {
  const { user, logout } = useAuth()
  const { t, gradeLabel } = useSchool()
  const location = useLocation()
  const navigate = useNavigate()

  const getRoleHeader = () => {
    if (!user) return null

    switch (user.role) {
      case "guardian":
        return (
          <div className="flex items-center space-x-2">
            <Users className="h-4 w-4 text-[#0066FF]" />
            <span className="font-medium text-[#122A42] text-sm hidden sm:inline">{user.name}</span>
            <Badge variant="info">{t("nav.family_code", { code: user.linked_entity_id })}</Badge>
          </div>
        )
      case "teacher":
        return (
          <div className="flex items-center space-x-2">
            <GraduationCap className="h-4 w-4 text-emerald-600" />
            <span className="font-medium text-[#122A42] text-sm hidden sm:inline">{user.name}</span>
            <Badge variant="success">
              {user.details?.taught_grade ? gradeLabel(Number(user.details.taught_grade)) : t("role.teacher")}
            </Badge>
          </div>
        )
      case "admin":
        return (
          <div className="flex items-center space-x-2">
            <ShieldCheck className="h-4 w-4 text-[#122A42]" />
            <span className="font-medium text-[#122A42] text-sm hidden sm:inline">{user.name}</span>
            <Badge className="bg-[#EDF4FA] text-[#122A42] border-[#D1DCE5]">{t("role.admin")}</Badge>
          </div>
        )
      default:
        return null
    }
  }

  return (
    <header className="sticky top-0 z-40 w-full border-b border-[#D1DCE5] bg-white/95 backdrop-blur">
      {user?.role === "admin" && (
        <div className="bg-[#122A42] text-slate-100 text-xs px-4 py-2 border-b border-[#27475c]">
          <div className="max-w-7xl mx-auto flex flex-col sm:flex-row items-center justify-between gap-2">
            <div className="flex items-center space-x-2">
              <ShieldCheck className="h-4 w-4 text-[#A4D0E9]" />
              <span className="font-semibold text-white">{t("nav.admin_mode")}</span>
              <span className="text-[#A4D0E9] hidden md:inline">{t("nav.admin_mode_hint")}</span>
            </div>
            <div className="flex items-center space-x-1 bg-[#27475c]/70 p-1 rounded-lg">
              <button
                type="button"
                onClick={() => navigate("/admin")}
                className={`px-3 py-1 rounded text-xs font-medium transition-colors ${
                  location.pathname === "/admin"
                    ? "bg-white text-[#122A42] font-bold shadow-sm"
                    : "text-slate-200 hover:bg-[#122A42] hover:text-white"
                }`}
              >
                {t("nav.admin_portal")}
              </button>
              <button
                type="button"
                onClick={() => navigate("/teacher")}
                className={`px-3 py-1 rounded text-xs font-medium transition-colors ${
                  location.pathname === "/teacher"
                    ? "bg-white text-[#122A42] font-bold shadow-sm"
                    : "text-slate-200 hover:bg-[#122A42] hover:text-white"
                }`}
              >
                {t("nav.view_as_teacher")}
              </button>
              <button
                type="button"
                onClick={() => navigate("/guardian")}
                className={`px-3 py-1 rounded text-xs font-medium transition-colors ${
                  location.pathname === "/guardian"
                    ? "bg-white text-[#122A42] font-bold shadow-sm"
                    : "text-slate-200 hover:bg-[#122A42] hover:text-white"
                }`}
              >
                {t("nav.view_as_guardian")}
              </button>
            </div>
          </div>
        </div>
      )}
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 h-16 flex items-center justify-between">
        {/* Brand */}
        <div className="flex items-center space-x-3 cursor-pointer" onClick={() => navigate("/")}>
          <img
            src="/logo_rounded.png"
            alt={t("app.logo_alt")}
            className="h-10 w-10 object-contain rounded-xl shadow-sm border border-[#A4D0E9]"
          />
          <div className="flex flex-col">
            <span className="font-bold text-[#122A42] leading-tight text-lg tracking-tight">Quickpass</span>
            <span className="text-[10px] text-[#4A607A] font-medium tracking-wider uppercase">{t("app.school_portal")}</span>
          </div>
        </div>

        {/* View Switcher Tabs */}
        <div className="flex items-center space-x-1 bg-[#EDF4FA] p-1 rounded-lg border border-[#D1DCE5]">
          <button
            type="button"
            onClick={() => onViewChange("day")}
            className={`flex items-center space-x-1.5 px-3 py-1.5 rounded-md text-xs sm:text-sm font-medium transition-all ${
              activeView === "day"
                ? "bg-white text-[#122A42] font-semibold shadow-sm"
                : "text-[#4A607A] hover:text-[#122A42]"
            }`}
          >
            <Clock className="h-3.5 w-3.5" />
            <span>{t("nav.day_view")}</span>
          </button>
          <button
            type="button"
            onClick={() => onViewChange("year")}
            className={`flex items-center space-x-1.5 px-3 py-1.5 rounded-md text-xs sm:text-sm font-medium transition-all ${
              activeView === "year"
                ? "bg-white text-[#122A42] font-semibold shadow-sm"
                : "text-[#4A607A] hover:text-[#122A42]"
            }`}
          >
            <Calendar className="h-3.5 w-3.5" />
            <span>{t("nav.year_view")}</span>
          </button>
        </div>

        {/* User Scope Info & Logout */}
        <div className="flex items-center space-x-3">
          {getRoleHeader()}
          <Button
            variant="ghost"
            size="sm"
            onClick={logout}
            className="text-[#4A607A] hover:text-rose-600 hover:bg-rose-50"
            title={t("nav.sign_out_title")}
          >
            <LogOut className="h-4 w-4" />
            <span className="hidden md:inline ml-1.5">{t("nav.sign_out")}</span>
          </Button>
        </div>
      </div>
    </header>
  )
}
