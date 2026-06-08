import { forwardRef, type InputHTMLAttributes } from "react"

// 统一的表单控件外观(填充式:浅灰底 → hover/聚焦变白 + teal 光晕环)。更大圆角、舒展内距,
// 比"白底细边"更有设计感。输入框/文本域/下拉共用,确保全站一致。
export const controlCls =
  "w-full rounded-xl border border-slate-200 bg-slate-100/70 px-3.5 py-2.5 text-sm text-slate-800 " +
  "placeholder:text-slate-400 outline-none transition " +
  "hover:border-slate-300 hover:bg-slate-50 " +
  "focus:border-brand-400 focus:bg-white focus:ring-4 focus:ring-brand-100/70 " +
  "disabled:cursor-not-allowed disabled:bg-slate-100 disabled:text-slate-400"

export const Input = forwardRef<HTMLInputElement, InputHTMLAttributes<HTMLInputElement>>(
  function Input({ className = "", ...props }, ref) {
    return <input ref={ref} className={`${controlCls} ${className}`} {...props} />
  },
)
