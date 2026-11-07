import { useState } from "react"
import { useNavigate } from "react-router-dom"
import { useAuth } from "@/context/AuthContext"
import { useSchool } from "@/context/SchoolContext"
import { ERR_UNAUTHORIZED_EMAIL } from "@/lib/supabase"
import type { MessageKey } from "@/lib/i18n"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from "@/components/ui/card"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { AlertCircle, CheckCircle2, KeyRound, LogIn, Shield, Zap, Bell, CheckCircle } from "lucide-react"

const MIN_PASSWORD_LENGTH = 6

export function LoginPage() {
  const { login, registerFirstTime, loginWithGoogle } = useAuth()
  const { t } = useSchool()
  const navigate = useNavigate()

  const errorText = (err: unknown, fallback: MessageKey) =>
    err instanceof Error && err.message === ERR_UNAUTHORIZED_EMAIL ? t("login.error.unauthorized_email") : t(fallback)
  const [hintBefore, hintAfter] = t("login.first_time.hint").split("{link}")

  // Standard Login State
  const [email, setEmail] = useState("")
  const [password, setPassword] = useState("")
  const [isLoading, setIsLoading] = useState(false)
  const [errorMsg, setErrorMsg] = useState<string | null>(null)

  // First-Time Activation Modal State
  const [isActivationOpen, setIsActivationOpen] = useState(false)
  const [actEmail, setActEmail] = useState("")
  const [actPassword, setActPassword] = useState("")
  const [actConfirmPassword, setActConfirmPassword] = useState("")
  const [actLoading, setActLoading] = useState(false)
  const [actError, setActError] = useState<string | null>(null)
  const [actSuccess, setActSuccess] = useState(false)

  const handleLogin = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!email || !password) return

    setIsLoading(true)
    setErrorMsg(null)

    try {
      const user = await login(email, password)
      navigate(`/${user.role}`)
    } catch (err) {
      setErrorMsg(errorText(err, "login.error.sign_in"))
    } finally {
      setIsLoading(false)
    }
  }

  const handleFirstTimeActivation = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!actEmail || !actPassword) return

    if (actPassword !== actConfirmPassword) {
      setActError(t("login.activation.mismatch"))
      return
    }

    if (actPassword.length < MIN_PASSWORD_LENGTH) {
      setActError(t("login.activation.too_short", { min: MIN_PASSWORD_LENGTH }))
      return
    }

    setActLoading(true)
    setActError(null)

    try {
      const user = await registerFirstTime(actEmail, actPassword)
      setActSuccess(true)
      setIsActivationOpen(false)
      navigate(`/${user.role}`)
    } catch (err) {
      setActError(errorText(err, "login.error.activation"))
    } finally {
      setActLoading(false)
    }
  }

  const handleGoogleSignIn = async () => {
    setIsLoading(true)
    setErrorMsg(null)
    try {
      const user = await loginWithGoogle()
      if (user) {
        navigate(`/${user.role}`)
      }
    } catch (err) {
      setErrorMsg(errorText(err, "login.error.google"))
    } finally {
      setIsLoading(false)
    }
  }

  return (
    <div className="flex min-h-screen w-screen bg-[#F4F8FB]">
      {/* LEFT COLUMN: Brand & System Showcase (Visible on Large Screens) */}
      <div className="hidden lg:flex lg:w-1/2 flex-col justify-between bg-gradient-to-br from-[#A4D0E9] via-[#93C3DF] to-[#80B5D5] p-12 text-[#122A42] border-r border-[#8CB8D4] shadow-inner relative overflow-hidden">
        {/* Subtle decorative background circles */}
        <div className="absolute -top-24 -left-24 w-96 h-96 rounded-full bg-white/15 blur-2xl pointer-events-none" />
        <div className="absolute -bottom-24 -right-24 w-96 h-96 rounded-full bg-[#122A42]/10 blur-2xl pointer-events-none" />

        {/* Top Branding Section */}
        <div className="relative z-10">
          <div className="flex items-center space-x-3 mb-8">
            <img
              src="/logo_rounded.png"
              alt={t("app.logo_alt")}
              className="h-12 w-12 object-contain rounded-2xl shadow-md border-2 border-white/80"
            />
            <div>
              <span className="text-2xl font-black tracking-tight text-[#122A42] block leading-none">
                Quickpass
              </span>
              <span className="text-xs uppercase tracking-widest font-bold text-[#27475c]">
                {t("app.school_portal")}
              </span>
            </div>
          </div>

          <div className="max-w-md">
            <h1 className="text-4xl font-extrabold tracking-tight text-[#122A42] leading-tight mb-4">
              {t("login.hero_title")}
            </h1>
            <p className="text-[#27475c] text-base leading-relaxed">
              {t("login.hero_text")}
            </p>
          </div>
        </div>

        {/* Feature Highlights & Parent Guide */}
        <div className="relative z-10 space-y-6 my-8">
          <div className="grid grid-cols-1 gap-3 max-w-md">
            <div className="flex items-start space-x-3.5 bg-white/60 backdrop-blur-md p-3.5 rounded-xl border border-white/80 shadow-sm">
              <div className="h-9 w-9 rounded-lg bg-[#122A42] text-white flex items-center justify-center shrink-0">
                <Zap className="h-5 w-5 text-[#A4D0E9]" />
              </div>
              <div>
                <h2 className="text-sm font-bold text-[#122A42]">{t("login.feature.instant_title")}</h2>
                <p className="text-xs text-[#27475c]">
                  {t("login.feature.instant_text")}
                </p>
              </div>
            </div>

            <div className="flex items-start space-x-3.5 bg-white/60 backdrop-blur-md p-3.5 rounded-xl border border-white/80 shadow-sm">
              <div className="h-9 w-9 rounded-lg bg-[#122A42] text-white flex items-center justify-center shrink-0">
                <Bell className="h-5 w-5 text-[#A4D0E9]" />
              </div>
              <div>
                <h2 className="text-sm font-bold text-[#122A42]">{t("login.feature.notifications_title")}</h2>
                <p className="text-xs text-[#27475c]">
                  {t("login.feature.notifications_text")}
                </p>
              </div>
            </div>

            <div className="flex items-start space-x-3.5 bg-white/60 backdrop-blur-md p-3.5 rounded-xl border border-white/80 shadow-sm">
              <div className="h-9 w-9 rounded-lg bg-[#122A42] text-white flex items-center justify-center shrink-0">
                <Shield className="h-5 w-5 text-[#A4D0E9]" />
              </div>
              <div>
                <h2 className="text-sm font-bold text-[#122A42]">{t("login.feature.security_title")}</h2>
                <p className="text-xs text-[#27475c]">
                  {t("login.feature.security_text")}
                </p>
              </div>
            </div>
          </div>

          {/* Activation hint for parents */}
          <div className="max-w-md bg-[#122A42]/90 text-white p-4 rounded-xl shadow-lg border border-[#122A42]">
            <div className="flex items-center space-x-2 text-sm font-bold text-[#A4D0E9] mb-1">
              <CheckCircle className="h-4 w-4" />
              <span>{t("login.first_time.title")}</span>
            </div>
            <p className="text-xs text-slate-200 leading-normal">
              {hintBefore}
              <strong>{t("login.activate_link")}</strong>
              {hintAfter}
            </p>
          </div>
        </div>

        {/* Footer info */}
        <div className="relative z-10 pt-4 border-t border-[#8CB8D4]/50 flex items-center justify-between text-xs text-[#27475c]">
          <span>{t("login.footer_system")}</span>
          <span className="font-semibold">{t("login.footer_version")}</span>
        </div>
      </div>

      {/* RIGHT COLUMN: Authentication Card */}
      <div className="w-full lg:w-1/2 flex items-center justify-center p-6 sm:p-12 overflow-y-auto">
        <div className="w-full max-w-md">
          {/* Mobile-only Branding Header */}
          <div className="mb-8 text-center lg:hidden">
            <img
              src="/logo_rounded.png"
              alt={t("app.logo_alt")}
              className="mx-auto mb-3 h-16 w-16 object-contain rounded-2xl shadow-md border-2 border-white"
            />
            <h1 className="text-2xl font-black tracking-tight text-[#122A42]">Quickpass</h1>
            <p className="mt-1 text-sm text-[#4A607A]">
              {t("login.tagline")}
            </p>
          </div>

          {/* Login Card */}
          <Card className="border-[#D1DCE5] shadow-xl shadow-slate-200/60 bg-white">
            <CardHeader className="space-y-1 pb-4">
              <CardTitle className="text-2xl font-bold text-[#122A42]">{t("login.title")}</CardTitle>
              <CardDescription className="text-sm text-[#4A607A]">
                {t("login.description")}
              </CardDescription>
            </CardHeader>

            <form onSubmit={handleLogin}>
              <CardContent className="space-y-4">
                {errorMsg && (
                  <Alert variant="destructive" className="animate-in fade-in duration-200">
                    <AlertCircle className="h-4 w-4" />
                    <AlertTitle>{t("login.access_denied")}</AlertTitle>
                    <AlertDescription>{errorMsg}</AlertDescription>
                  </Alert>
                )}

                <div className="space-y-1.5">
                  <Label htmlFor="email" className="text-[#122A42] font-medium text-sm">
                    {t("login.email_label")}
                  </Label>
                  <Input
                    id="email"
                    type="email"
                    placeholder={t("login.email_placeholder")}
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    className="border-[#B8C8D6] focus-visible:ring-[#0066FF]"
                    required
                  />
                </div>

                <div className="space-y-1.5">
                  <div className="flex items-center justify-between">
                    <Label htmlFor="password" className="text-[#122A42] font-medium text-sm">
                      {t("login.password_label")}
                    </Label>
                    <button
                      type="button"
                      onClick={() => {
                        setActEmail(email)
                        setIsActivationOpen(true)
                      }}
                      className="text-xs font-semibold text-[#0066FF] hover:underline cursor-pointer"
                    >
                      {t("login.activate_link")}
                    </button>
                  </div>
                  <Input
                    id="password"
                    type="password"
                    placeholder="••••••••"
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    className="border-[#B8C8D6] focus-visible:ring-[#0066FF]"
                    required
                  />
                </div>

                <Button
                  type="submit"
                  className="w-full bg-[#0066FF] hover:bg-[#0052CC] text-white font-semibold py-2.5 shadow-md shadow-blue-500/20"
                  disabled={isLoading}
                >
                  {isLoading ? (
                    <div className="h-5 w-5 animate-spin rounded-full border-2 border-white border-t-transparent" />
                  ) : (
                    <>
                      <LogIn className="mr-2 h-4 w-4" />
                      {t("login.submit")}
                    </>
                  )}
                </Button>

                <div className="relative my-4">
                  <div className="absolute inset-0 flex items-center">
                    <div className="w-full border-t border-[#D1DCE5]" />
                  </div>
                  <div className="relative flex justify-center text-xs uppercase">
                    <span className="bg-white px-2 text-[#4A607A] font-medium">{t("login.or_continue")}</span>
                  </div>
                </div>

                <Button
                  type="button"
                  variant="outline"
                  className="w-full border-[#B8C8D6] font-medium text-[#122A42] hover:bg-[#EDF4FA]"
                  onClick={handleGoogleSignIn}
                  disabled={isLoading}
                >
                  <svg className="mr-2 h-4 w-4" viewBox="0 0 24 24">
                    <path
                      fill="#4285F4"
                      d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z"
                    />
                    <path
                      fill="#34A853"
                      d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z"
                    />
                    <path
                      fill="#FBBC05"
                      d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.06H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.94l2.85-2.22.81-.63z"
                    />
                    <path
                      fill="#EA4335"
                      d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.06l3.66 2.84c.87-2.6 3.3-4.52 6.16-4.52z"
                    />
                  </svg>
                  {t("login.google")}
                </Button>
              </CardContent>

              <CardFooter className="flex flex-col space-y-2 border-t border-[#D1DCE5] bg-[#F4F8FB]/60 pt-4 text-center rounded-b-xl">
                <p className="text-xs text-[#4A607A]">
                  {t("login.no_access")}
                </p>
              </CardFooter>
            </form>
          </Card>
        </div>
      </div>

      {/* First-Time Activation Modal */}
      <Dialog open={isActivationOpen} onOpenChange={setIsActivationOpen}>
        <DialogHeader>
          <div className="flex items-center space-x-2">
            <KeyRound className="h-5 w-5 text-[#0066FF]" />
            <DialogTitle className="text-xl font-bold text-[#122A42]">{t("login.activation.title")}</DialogTitle>
          </div>
          <DialogDescription className="text-sm text-[#4A607A]">
            {t("login.activation.description")}
          </DialogDescription>
        </DialogHeader>

        <form onSubmit={handleFirstTimeActivation}>
          <DialogContent className="space-y-4">
            {actError && (
              <Alert variant="destructive">
                <AlertCircle className="h-4 w-4" />
                <AlertDescription>{actError}</AlertDescription>
              </Alert>
            )}

            {actSuccess && (
              <Alert variant="success">
                <CheckCircle2 className="h-4 w-4" />
                <AlertDescription>{t("login.activation.success")}</AlertDescription>
              </Alert>
            )}

            <div className="space-y-1.5">
              <Label htmlFor="act-email" className="text-[#122A42] font-medium text-sm">
                {t("login.activation.email_label")}
              </Label>
              <Input
                id="act-email"
                type="email"
                placeholder={t("login.activation.email_placeholder")}
                value={actEmail}
                onChange={(e) => setActEmail(e.target.value)}
                className="border-[#B8C8D6] focus-visible:ring-[#0066FF]"
                required
              />
            </div>

            <div className="space-y-1.5">
              <Label htmlFor="act-password" className="text-[#122A42] font-medium text-sm">
                {t("login.activation.password_label")}
              </Label>
              <Input
                id="act-password"
                type="password"
                placeholder={t("login.activation.password_placeholder", { min: MIN_PASSWORD_LENGTH })}
                value={actPassword}
                onChange={(e) => setActPassword(e.target.value)}
                className="border-[#B8C8D6] focus-visible:ring-[#0066FF]"
                required
              />
            </div>

            <div className="space-y-1.5">
              <Label htmlFor="act-confirm" className="text-[#122A42] font-medium text-sm">
                {t("login.activation.confirm_label")}
              </Label>
              <Input
                id="act-confirm"
                type="password"
                placeholder={t("login.activation.confirm_placeholder")}
                value={actConfirmPassword}
                onChange={(e) => setActConfirmPassword(e.target.value)}
                className="border-[#B8C8D6] focus-visible:ring-[#0066FF]"
                required
              />
            </div>
          </DialogContent>

          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              onClick={() => setIsActivationOpen(false)}
              disabled={actLoading}
              className="border-[#B8C8D6] text-[#122A42]"
            >
              {t("common.cancel")}
            </Button>
            <Button
              type="submit"
              disabled={actLoading || actSuccess}
              className="bg-[#0066FF] hover:bg-[#0052CC] text-white font-semibold"
            >
              {actLoading ? t("login.activation.submitting") : t("login.activation.submit")}
            </Button>
          </DialogFooter>
        </form>
      </Dialog>
    </div>
  )
}
