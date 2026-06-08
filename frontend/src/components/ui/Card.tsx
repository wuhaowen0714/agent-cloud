import type { ReactNode } from "react"

/** 圆角 + 细边 + 柔和阴影的白色表面,撑起「有质感」的层次。 */
export function Card({ className = "", children }: { className?: string; children: ReactNode }) {
  return (
    <div className={`rounded-2xl border border-slate-200/80 bg-white shadow-card ${className}`}>
      {children}
    </div>
  )
}
