import * as React from "react"
import { cn } from "@/lib/utils"

export function Dialog({
  open,
  onOpenChange,
  children,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  children: React.ReactNode
}) {
  if (!open) return null

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/50 backdrop-blur-sm animate-in fade-in duration-150">
      <div className="fixed inset-0" onClick={() => onOpenChange(false)} />
      <div className="relative z-50 w-full max-w-lg bg-white rounded-xl shadow-2xl border border-slate-200 overflow-hidden animate-in zoom-in-95 duration-150">
        {children}
      </div>
    </div>
  )
}

export function DialogHeader({
  className,
  children,
}: {
  className?: string
  children: React.ReactNode
}) {
  return (
    <div className={cn("flex flex-col space-y-1.5 p-6 border-b border-slate-100", className)}>
      {children}
    </div>
  )
}

export function DialogTitle({
  className,
  children,
}: {
  className?: string
  children: React.ReactNode
}) {
  return (
    <h3 className={cn("text-lg font-semibold text-slate-900", className)}>
      {children}
    </h3>
  )
}

export function DialogDescription({
  className,
  children,
}: {
  className?: string
  children: React.ReactNode
}) {
  return (
    <p className={cn("text-sm text-slate-500", className)}>
      {children}
    </p>
  )
}

export function DialogContent({
  className,
  children,
}: {
  className?: string
  children: React.ReactNode
}) {
  return (
    <div className={cn("p-6", className)}>
      {children}
    </div>
  )
}

export function DialogFooter({
  className,
  children,
}: {
  className?: string
  children: React.ReactNode
}) {
  return (
    <div className={cn("flex items-center justify-end space-x-2 p-6 border-t border-slate-100 bg-slate-50", className)}>
      {children}
    </div>
  )
}
