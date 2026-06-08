import type { ButtonHTMLAttributes } from "react"

type Variant = "primary" | "secondary" | "ghost" | "danger"
type Size = "sm" | "md"

const BASE =
  "inline-flex items-center justify-center gap-1.5 rounded-xl font-medium transition " +
  "focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-brand-100/70 " +
  "disabled:cursor-not-allowed disabled:opacity-50 disabled:shadow-none"

const VARIANTS: Record<Variant, string> = {
  // teal 渐变主按钮 + 轻阴影,是「有质感」的主操作
  primary:
    "bg-gradient-to-b from-brand-500 to-brand-600 text-white shadow-sm " +
    "hover:from-brand-600 hover:to-brand-700 active:from-brand-700 active:to-brand-800",
  secondary:
    "border border-slate-200 bg-white text-slate-700 shadow-sm hover:bg-slate-50 hover:border-slate-300",
  ghost: "text-slate-600 hover:bg-slate-100",
  danger: "bg-red-600 text-white shadow-sm hover:bg-red-700",
}

const SIZES: Record<Size, string> = {
  sm: "px-3 py-1.5 text-xs",
  md: "px-4 py-2.5 text-sm",
}

export function Button({
  variant = "primary",
  size = "md",
  className = "",
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant; size?: Size }) {
  return (
    <button className={`${BASE} ${VARIANTS[variant]} ${SIZES[size]} ${className}`} {...props} />
  )
}
