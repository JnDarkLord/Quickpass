import * as React from "react"
import { cn } from "@/lib/utils"

export interface BadgeProps extends React.HTMLAttributes<HTMLDivElement> {
  variant?: "default" | "success" | "warning" | "destructive" | "outline" | "info"
}

export function Badge({ className, variant = "default", ...props }: BadgeProps) {
  const variants = {
    default: "bg-slate-900 text-white hover:bg-slate-800",
    success: "bg-emerald-50 text-emerald-700 border border-emerald-200 font-semibold",
    warning: "bg-amber-50 text-amber-700 border border-amber-200 font-semibold",
    destructive: "bg-rose-50 text-rose-700 border border-rose-200 font-semibold",
    info: "bg-blue-50 text-blue-700 border border-blue-200 font-semibold",
    outline: "text-slate-900 border border-slate-200",
  }

  return (
    <div
      className={cn(
        "inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium transition-colors select-none",
        variants[variant],
        className
      )}
      {...props}
    />
  )
}
