import ReactMarkdown from "react-markdown"
import remarkGfm from "remark-gfm"

// assistant 正文按 markdown 渲染。react-markdown 输出 React 元素(自动转义,无 XSS)。
// prose 提供排版;max-w-none 让宽度由气泡控制;code/pre 适配浅色 + teal。
// ⚠️ 安全:本组件同时渲染聊天正文与【工作区文件预览】(任意生成内容)——
// 绝不可引入 rehype-raw / 放开 urlTransform,否则两处同时变成可利用的存储型 XSS。
// prose-code:text-brand-700 的 :where() 选择器命中 prose 内所有 code(含 pre>code),
// utility 后加载胜出 → 深 teal 落在 prose-pre 深底上看不清。[&_pre_code]:text-inherit
// 以真实后代选择器特异性压回:代码块继承 pre 的 text-slate-100,行内 code 的 teal 不变。
export function Markdown({ children }: { children: string }) {
  return (
    <div className="prose prose-sm prose-slate max-w-none prose-pre:bg-slate-800 prose-pre:text-slate-100 prose-code:text-brand-700 prose-code:before:content-none prose-code:after:content-none [&_pre_code]:text-inherit">
      <ReactMarkdown remarkPlugins={[remarkGfm]}>{children}</ReactMarkdown>
    </div>
  )
}
