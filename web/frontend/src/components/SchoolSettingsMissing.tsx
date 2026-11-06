import type { ReactNode } from "react"
import { LANGUAGES, translate } from "@/lib/i18n"

function Notice({ children }: { children: ReactNode }) {
  return (
    <div className="flex min-h-screen w-screen items-center justify-center bg-slate-50 p-6">
      <div className="max-w-lg space-y-3 rounded-xl border border-slate-200 bg-white p-6 shadow-sm">{children}</div>
    </div>
  )
}

/** Until the School saves its School Settings there is no School Language, so this speaks English, like the setup guides. */
export function NotSetUpYet() {
  return (
    <Notice>
      <div lang="en" className="space-y-3">
        <h1 className="text-lg font-bold text-slate-900">Quickpass is not set up yet</h1>
        <p className="text-sm text-slate-600">
          Start the desktop program on a station with Cloud Sync turned on and finish its setup wizard, where the
          School chooses its School Language. Refresh this page once the station has sent the School Settings to
          Supabase.
        </p>
      </div>
    </Notice>
  )
}

/** The School Language is one of the settings that could not be read, so this says so in every language. */
export function SchoolSettingsUnavailable() {
  return (
    <Notice>
      {LANGUAGES.map((lang) => (
        <p key={lang} lang={lang} className="text-sm text-slate-600">
          {translate(lang, "app.settings_unavailable")}
        </p>
      ))}
    </Notice>
  )
}
