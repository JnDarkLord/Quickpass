/**
 * School Language text: key-based catalogs and each language's date and time conventions.
 *
 * Every School-facing text has a dot-separated key with one entry per language in
 * `locales/es.json` and `locales/en.json`. Code passes keys and neutral values
 * around and turns them into text only where a person reads it.
 */
import es from "@/locales/es.json"
import en from "@/locales/en.json"

export const LANGUAGES = ["es", "en"] as const
export type Language = (typeof LANGUAGES)[number]

type Catalog = typeof es
type KeysOf<T, Prefix extends string = ""> = {
  [K in keyof T & string]: T[K] extends string ? `${Prefix}${K}` : KeysOf<T[K], `${Prefix}${K}.`>
}[keyof T & string]

/** A dot-separated catalog key, such as `login.title`. */
export type MessageKey = KeysOf<Catalog>
export type MessageParams = Record<string, string | number>
export interface TimeOptions {
  seconds?: boolean
}

const catalogs: Record<Language, Catalog> = { es, en }

function flatten(tree: object, prefix = ""): Record<string, string> {
  const flat: Record<string, string> = {}
  for (const [name, value] of Object.entries(tree)) {
    if (value !== null && typeof value === "object") {
      Object.assign(flat, flatten(value, `${prefix}${name}.`))
    } else {
      flat[`${prefix}${name}`] = String(value)
    }
  }
  return flat
}

const texts = {
  es: flatten(catalogs.es),
  en: flatten(catalogs.en),
} satisfies Record<Language, Record<string, string>>

const DATE_PATTERNS: Record<Language, string> = { es: "DD/MM/YYYY", en: "MM/DD/YYYY" }
const SHORT_DATE_PATTERNS: Record<Language, string> = { es: "DD/MM", en: "MM/DD" }
const TWELVE_HOUR_CLOCK: Record<Language, boolean> = { es: false, en: true }
const INTL_LOCALES: Record<Language, string> = { es: "es-ES", en: "en-US" }

export function isLanguage(value: unknown): value is Language {
  return LANGUAGES.includes(value as Language)
}

/** The text for `key` in `lang`, with `{name}` placeholders filled in from `params`. */
export function translate(lang: Language, key: MessageKey, params?: MessageParams): string {
  const text = texts[lang][key] ?? key
  if (!params) {
    return text
  }
  return text.replace(/\{(\w+)\}/g, (placeholder, name: string) =>
    name in params ? String(params[name]) : placeholder
  )
}

const ISO_DATE = /^(\d{4})-(\d{2})-(\d{2})/
const CLOCK_TIME = /^(\d{1,2}):(\d{2})(?::(\d{2}))?/

function fillDate(pattern: string, isoDate: string): string {
  const match = ISO_DATE.exec(isoDate)
  if (!match) {
    return isoDate
  }
  const [, year, month, day] = match
  return pattern.replace("YYYY", year).replace("MM", month).replace("DD", day)
}

/** Spanish writes DD/MM/YYYY; English writes MM/DD/YYYY. Dates arrive as ISO YYYY-MM-DD. */
export function formatDate(lang: Language, isoDate: string): string {
  return fillDate(DATE_PATTERNS[lang], isoDate)
}

/** The day and month alone, in the order `formatDate` writes them. */
export function formatShortDate(lang: Language, isoDate: string): string {
  return fillDate(SHORT_DATE_PATTERNS[lang], isoDate)
}

/** Spanish writes 24-hour HH:MM:SS; English writes 12-hour hh:mm:ss AM/PM. Times arrive as HH:MM:SS. */
export function formatTime(lang: Language, clock: string, { seconds = true }: TimeOptions = {}): string {
  const match = CLOCK_TIME.exec(clock)
  if (!match) {
    return clock
  }
  const [, hours, minutes, secs = "00"] = match
  const rest = seconds ? `${minutes}:${secs}` : minutes
  if (!TWELVE_HOUR_CLOCK[lang]) {
    return `${hours.padStart(2, "0")}:${rest}`
  }
  const hour = Number(hours)
  return `${String(hour % 12 || 12).padStart(2, "0")}:${rest} ${hour < 12 ? "AM" : "PM"}`
}

/** The month's name and year, such as "octubre de 2026" or "October 2026". */
export function formatMonth(lang: Language, month: Date): string {
  return month.toLocaleString(INTL_LOCALES[lang], { month: "long", year: "numeric" })
}
