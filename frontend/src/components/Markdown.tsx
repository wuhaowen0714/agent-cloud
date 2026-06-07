import ReactMarkdown from "react-markdown"
import remarkGfm from "remark-gfm"

// assistant 正文按 markdown 渲染。react-markdown 输出 React 元素(自动转义,无 XSS)。
// prose 提供排版;max-w-none 让宽度由气泡控制;code/pre 适配浅色 + teal。
export function Markdown({ children }: { children: string }) {
  return (
    <div className="prose prose-sm prose-slate max-w-none prose-pre:bg-slate-800 prose-pre:text-slate-100 prose-code:text-brand-700 prose-code:before:content-none prose-code:after:content-none">
      <ReactMarkdown remarkPlugins={[remarkGfm]}>{children}</ReactMarkdown>
    </div>
  )
}
