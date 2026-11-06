import { describe, it, expect } from "vitest"
import es from "@/locales/es.json"
import en from "@/locales/en.json"
import { formatDate, formatShortDate, formatTime, translate } from "@/lib/i18n"

function flatten(tree: object, prefix = ""): Record<string, unknown> {
  return Object.entries(tree).reduce<Record<string, unknown>>((flat, [name, value]) => {
    const key = `${prefix}${name}`
    return value !== null && typeof value === "object"
      ? { ...flat, ...flatten(value, `${key}.`) }
      : { ...flat, [key]: value }
  }, {})
}

function placeholders(text: unknown): string[] {
  return [...String(text).matchAll(/\{(\w+)\}/g)].map((match) => match[1]).sort()
}

describe("Portal catalogs", () => {
  const spanish = flatten(es)
  const english = flatten(en)

  it("carry the same keys in Spanish and English", () => {
    expect(Object.keys(english).sort()).toEqual(Object.keys(spanish).sort())
  })

  it("fill in every text and use the same placeholders in both languages", () => {
    for (const [key, text] of Object.entries(spanish)) {
      expect(typeof text === "string" && text.trim(), `es: ${key}`).toBeTruthy()
      expect(typeof english[key] === "string" && String(english[key]).trim(), `en: ${key}`).toBeTruthy()
      expect(placeholders(english[key]), key).toEqual(placeholders(text))
    }
  })

  it("fill in placeholders from the values given", () => {
    expect(translate("es", "guardian.family_title", { name: "Mendoza" })).toBe("Familia Mendoza")
    expect(translate("en", "guardian.family_title", { name: "Mendoza" })).toBe("Family Mendoza")
  })
})

describe("School Language formats", () => {
  it("write Spanish dates as DD/MM/YYYY and times on the 24-hour clock", () => {
    expect(formatDate("es", "2026-03-09")).toBe("09/03/2026")
    expect(formatShortDate("es", "2026-03-09")).toBe("09/03")
    expect(formatTime("es", "13:05:09")).toBe("13:05:09")
    expect(formatTime("es", "00:00:00")).toBe("00:00:00")
    expect(formatTime("es", "06:50:00", { seconds: false })).toBe("06:50")
  })

  it("write English dates as MM/DD/YYYY and times on the 12-hour clock with AM/PM", () => {
    expect(formatDate("en", "2026-03-09")).toBe("03/09/2026")
    expect(formatShortDate("en", "2026-12-25")).toBe("12/25")
    expect(formatTime("en", "13:05:09")).toBe("01:05:09 PM")
    expect(formatTime("en", "00:00:00")).toBe("12:00:00 AM")
    expect(formatTime("en", "12:00:00")).toBe("12:00:00 PM")
    expect(formatTime("en", "06:50:00", { seconds: false })).toBe("06:50 AM")
  })
})
