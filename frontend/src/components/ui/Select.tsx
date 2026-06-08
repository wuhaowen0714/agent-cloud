import { forwardRef, type SelectHTMLAttributes } from "react"
import { controlCls } from "./Input"

// 原生 select 太丑:appearance-none 去掉系统箭头,自绘一个统一的 chevron,并与输入框同款外观。
export const Select = forwardRef<HTMLSelectElement, SelectHTMLAttributes<HTMLSelectElement>>(
  function Select({ className = "", children, ...props }, ref) {
    return (
      <div className="relative">
        <select
          ref={ref}
          className={`${controlCls} cursor-pointer appearance-none pr-9 ${className}`}
          {...props}
        >
          {children}
        </select>
        <svg
          className="pointer-events-none absolute right-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400"
          viewBox="0 0 20 20"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.6"
        >
          <path d="M6 8l4 4 4-4" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      </div>
    )
  },
)
