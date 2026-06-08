import { forwardRef, type TextareaHTMLAttributes } from "react"
import { controlCls } from "./Input"

export const Textarea = forwardRef<HTMLTextAreaElement, TextareaHTMLAttributes<HTMLTextAreaElement>>(
  function Textarea({ className = "", ...props }, ref) {
    return <textarea ref={ref} className={`${controlCls} resize-none ${className}`} {...props} />
  },
)
