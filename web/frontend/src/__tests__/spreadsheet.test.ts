import { afterEach, describe, expect, it, vi } from "vitest"
import { buildCsv, buildSheetData, exportRows, safeSheetName } from "@/lib/spreadsheet"

const rows = [
  { Name: "Mendoza, Valeria", Grade: "5°", "Present days": 12, Note: 'Said "hi"' },
  { Name: "=HYPERLINK(\"x\")", Grade: "5°", "Present days": 0, Note: null },
]

describe("spreadsheet exports", () => {
  afterEach(() => vi.restoreAllMocks())

  it("writes RFC 4180 CSV with a BOM, quoting, and formula-injection guard", () => {
    expect(buildCsv(rows)).toBe(
      "﻿Name,Grade,Present days,Note\r\n" +
      '"Mendoza, Valeria",5°,12,"Said ""hi"""\r\n' +
      "\"'=HYPERLINK(\"\"x\"\")\",5°,0,\r\n",
    )
  })

  it("keeps placeholder dashes and negative numbers unchanged in CSV", () => {
    expect(buildCsv([{ Time: "--", Delta: -3 }])).toBe("﻿Time,Delta\r\n--,-3\r\n")
  })

  it("builds sheet data with a bold header row and typed cells", () => {
    const data = buildSheetData(rows)
    expect(data[0]).toEqual([
      { value: "Name", fontWeight: "bold" },
      { value: "Grade", fontWeight: "bold" },
      { value: "Present days", fontWeight: "bold" },
      { value: "Note", fontWeight: "bold" },
    ])
    expect(data[1][2]).toEqual({ type: Number, value: 12 })
    expect(data[2][3]).toBeNull()
  })

  it("makes sheet names valid for Excel", () => {
    expect(safeSheetName("Attendance [2026/10]: all")).toBe("Attendance _2026_10__ all")
    expect(safeSheetName("x".repeat(40))).toHaveLength(31)
    expect(safeSheetName("")).toBe("Sheet1")
  })

  it.each(["xlsx", "csv"] as const)("downloads a %s file under the given name", async (format) => {
    const createObjectURL = vi.fn((_: Blob) => "blob:quickpass")
    Object.assign(URL, { createObjectURL, revokeObjectURL: vi.fn() })
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (this: HTMLAnchorElement) {
      expect(this.download).toBe(`Report.${format}`)
      expect(this.href).toBe("blob:quickpass")
    })

    await exportRows(rows, { sheetName: "Report", fileName: `Report.${format}`, format })

    expect(click).toHaveBeenCalledOnce()
    const blob = createObjectURL.mock.calls[0][0]
    expect(blob.size).toBeGreaterThan(0)
    if (format === "xlsx") {
      // An .xlsx file is a ZIP archive.
      const signature = new Uint8Array(await blob.arrayBuffer()).slice(0, 2)
      expect(String.fromCharCode(...signature)).toBe("PK")
    }
  })
})
