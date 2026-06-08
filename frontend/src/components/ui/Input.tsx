import { forwardRef, type InputHTMLAttributes } from "react"

// 统一的表单控件外观:圆角 + 细边 + 轻阴影 + teal 聚焦环;disabled 态明确。
// 输入框/文本域/下拉共用,确保全站一致。
export const controlCls =
  "w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm text-slate-800 shadow-sm " +
  "placeholder:text-slate-400 outline-none transition " +
  "focus:border-brand-500 focus:ring-2 focus:ring-brand-100 " +
  "disabled:cursor-not-allowed disabled:bg-slate-50 disabled:text-slate-400"

export const Input = forwardRef<HTMLInputElement, InputHTMLAttributes<HTMLInputElement>>(
  function Input({ className = "", ...props }, ref) {
    return <input ref={ref} className={`${controlCls} ${className}`} {...props} />
  },
)
