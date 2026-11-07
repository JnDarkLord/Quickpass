import { type ClassValue, clsx } from "clsx"
import { twMerge } from "tailwind-merge"

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

/** Today's date where the portal is open, as YYYY-MM-DD; the UTC date is already tomorrow on a School's evening west of Greenwich. */
export function localToday(): string {
  const now = new Date()
  const pad = (n: number) => String(n).padStart(2, "0")
  return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`
}

/** A file name with the characters file systems forbid replaced by dashes, as the desktop reports do. */
export function safeFileName(name: string): string {
  return name.replace(/[/\\:*?"<>|]/g, "-")
}
