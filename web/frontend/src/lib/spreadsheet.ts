import writeXlsxFile from "write-excel-file/browser"
import type { SheetData } from "write-excel-file/browser"

// Writes the portal's exports: one sheet of rows, as an Excel workbook or a CSV file.
// The keys of the first row are the column headers, in order.

export type SpreadsheetFormat = "xlsx" | "csv"
export type SpreadsheetValue = string | number | null | undefined
export type SpreadsheetRow = Record<string, SpreadsheetValue>

export interface ExportOptions {
  sheetName: string
  fileName: string
  format: SpreadsheetFormat
}

export async function exportRows(rows: SpreadsheetRow[], { sheetName, fileName, format }: ExportOptions): Promise<void> {
  const blob = format === "csv"
    ? new Blob([buildCsv(rows)], { type: "text/csv;charset=utf-8" })
    : await writeXlsxFile(buildSheetData(rows), { sheet: safeSheetName(sheetName) }).toBlob()
  downloadBlob(blob, fileName)
}

function headersOf(rows: SpreadsheetRow[]): string[] {
  return rows.length > 0 ? Object.keys(rows[0]) : []
}

export function buildSheetData(rows: SpreadsheetRow[]): SheetData {
  const headers = headersOf(rows)
  return [
    headers.map((header) => ({ value: header, fontWeight: "bold" as const })),
    ...rows.map((row) => headers.map((header) => {
      const value = row[header]
      if (value === null || value === undefined) return null
      return typeof value === "number" ? { type: Number, value } : { type: String, value }
    })),
  ]
}

// RFC 4180 CSV with a UTF-8 byte order mark, so Excel opens accented names correctly.
export function buildCsv(rows: SpreadsheetRow[]): string {
  const headers = headersOf(rows)
  const lines = [headers, ...rows.map((row) => headers.map((header) => row[header]))]
  return "﻿" + lines.map((cells) => cells.map(csvCell).join(",")).join("\r\n") + "\r\n"
}

function csvCell(value: SpreadsheetValue): string {
  if (value === null || value === undefined) return ""
  let text = String(value)
  // A cell starting with one of these runs as a formula in spreadsheet apps (CSV injection).
  if (typeof value === "string" && /^[=+@\t\r]/.test(text)) text = `'${text}`
  return /[",\r\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text
}

// Excel sheet names: at most 31 characters, without \ / ? * [ ] :
export function safeSheetName(name: string): string {
  return name.replace(/[\\/?*[\]:]/g, "_").slice(0, 31) || "Sheet1"
}

function downloadBlob(blob: Blob, fileName: string): void {
  const url = URL.createObjectURL(blob)
  const link = document.createElement("a")
  link.href = url
  link.download = fileName
  document.body.appendChild(link)
  link.click()
  link.remove()
  setTimeout(() => URL.revokeObjectURL(url), 0)
}
