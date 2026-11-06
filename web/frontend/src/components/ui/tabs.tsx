import * as React from "react"
import { cn } from "@/lib/utils"

interface TabsContextType {
  value: string
  onValueChange: (val: string) => void
}

const TabsContext = React.createContext<TabsContextType | null>(null)

export function Tabs({
  value,
  onValueChange,
  className,
  children,
}: {
  value: string
  onValueChange: (val: string) => void
  className?: string
  children: React.ReactNode
}) {
  return (
    <TabsContext.Provider value={{ value, onValueChange }}>
      <div className={cn("w-full", className)}>{children}</div>
    </TabsContext.Provider>
  )
}

export function TabsList({
  className,
  children,
}: {
  className?: string
  children: React.ReactNode
}) {
  return (
    <div
      className={cn(
        "inline-flex h-11 items-center justify-center rounded-xl bg-slate-100 p-1 text-slate-500",
        className
      )}
    >
      {children}
    </div>
  )
}

export function TabsTrigger({
  value,
  className,
  children,
}: {
  value: string
  className?: string
  children: React.ReactNode
}) {
  const ctx = React.useContext(TabsContext)
  if (!ctx) throw new Error("TabsTrigger must be inside Tabs")

  const isSelected = ctx.value === value

  return (
    <button
      type="button"
      onClick={() => ctx.onValueChange(value)}
      className={cn(
        "inline-flex items-center justify-center whitespace-nowrap rounded-lg px-3.5 py-1.5 text-sm font-medium ring-offset-white transition-all focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-950 focus-visible:ring-offset-2 disabled:pointer-events-none disabled:opacity-50 cursor-pointer select-none",
        isSelected
          ? "bg-white text-slate-900 shadow-sm"
          : "hover:bg-slate-200/60 hover:text-slate-900",
        className
      )}
    >
      {children}
    </button>
  )
}

export function TabsContent({
  value,
  className,
  children,
}: {
  value: string
  className?: string
  children: React.ReactNode
}) {
  const ctx = React.useContext(TabsContext)
  if (!ctx) throw new Error("TabsContent must be inside Tabs")

  if (ctx.value !== value) return null

  return (
    <div
      className={cn(
        "mt-4 ring-offset-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-slate-950 focus-visible:ring-offset-2 animate-in fade-in-50 duration-200",
        className
      )}
    >
      {children}
    </div>
  )
}
