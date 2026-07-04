import "katex/dist/katex.min.css"
import { memo } from "react"
import type { ReactNode } from "react"
import ReactMarkdown from "react-markdown"
import rehypeHighlight from "rehype-highlight"
import rehypeKatex from "rehype-katex"
import remarkGfm from "remark-gfm"
import remarkMath from "remark-math"

// LLM 几乎都用 \( … \) / \[ … \] 包裹数学(而非 remark-math 默认认的 $ / $$),且 react-markdown
// 把 \( 当「转义括号」直接渲成 (,数学根本进不了 remark-math。故先归一化:\(…\)→$…$、\[…\]→$$…$$,
// 再走 remark-math + rehype-katex。非贪婪 + [\s\S] 支持跨行 display 公式;只换成对定界符,孤立的
// \( 不动。代码块内出现成对 LaTeX 定界符极罕见,接受这点边角。已是 $ / $$ 的输入原样交给 remark-math。
function normalizeMath(s: string): string {
  return s
    // display 数学是块级:用空行裹成独占段落,remark-math 才出 .katex-display(居中大号)
    .replace(/\\\[([\s\S]+?)\\\]/g, (_m, body) => "\n\n$$\n" + body.trim() + "\n$$\n\n")
    .replace(/\\\(([\s\S]+?)\\\)/g, (_m, body) => "$" + body.trim() + "$")
}

// assistant 正文按 markdown 渲染。react-markdown 输出 React 元素(自动转义,无 XSS)。
// prose 提供排版;max-w-none 让宽度由气泡控制;code/pre 适配浅色 + teal。
// ⚠️ 安全:本组件同时渲染聊天正文与【工作区文件预览】(任意生成内容)——
// 绝不可引入 rehype-raw / 放开 urlTransform,否则两处同时变成可利用的存储型 XSS。
// (rehype-highlight 只把代码【文本】切成 hljs span;rehype-katex 产出 KaTeX 受控标记,trust 默认
// false 禁用 \href/\includegraphics 等危险命令——两者都不解析原始 HTML,不碰这条红线。)
// throwOnError:false → 坏公式就地渲成红字而非崩掉整条消息;strict:false → best-effort 不报警。
// prose-code:text-brand-700 的 :where() 选择器命中 prose 内所有 code(含 pre>code),
// utility 后加载胜出 → 深 teal 落在 prose-pre 深底上看不清。[&_pre_code]:text-inherit
// 以真实后代选择器特异性压回:代码块继承 pre 的 text-slate-100,行内 code 的 teal 不变。
// 高亮只认 ```lang 标注(common ~37 语言),不开自动探测:探测要对整块文本跑全部语法,
// 大文件预览/流式重渲染下是纯浪费,LLM 输出几乎总带语言标注。token 配色在 index.css。
// memo:流式期间 MessageList 每个 delta 都重渲染,历史回合的 Markdown 文本不变——
// 跳过它们的重解析+重高亮(live 块 children 在变,照常更新)。
// 工作区路径链接(可选,聊天正文启用):inline code 文本命中传入的解析器 → 渲染成可点
// 击的 code 样式按钮(打开文件预览 / 文件管理定位)。仅替换渲染出的 React 元素,不引入
// 任何原始 HTML,不触碰上方 XSS 红线。block code(className 带 language- 或含换行)不处理。
export const Markdown = memo(function Markdown({
  children,
  resolvePath,
  onOpenPath,
}: {
  children: string
  resolvePath?: (text: string) => { path: string; isDir: boolean } | null
  onOpenPath?: (hit: { path: string; isDir: boolean }) => void
}) {
  const components =
    resolvePath && onOpenPath
      ? {
          code: ({ className, children: c, ...rest }: { className?: string; children?: ReactNode }) => {
            const text =
              typeof c === "string"
                ? c
                : Array.isArray(c) && c.every((x) => typeof x === "string")
                  ? c.join("")
                  : null
            const isInline =
              text !== null && !text.includes("\n") && !(className ?? "").includes("language-")
            const hit = isInline && text ? resolvePath(text) : null
            if (!hit) {
              return (
                <code className={className} {...rest}>
                  {c}
                </code>
              )
            }
            return (
              <button
                type="button"
                onClick={() => onOpenPath(hit)}
                title={hit.isDir ? "在文件管理中打开" : "预览文件"}
                className="cursor-pointer rounded bg-brand-50 px-1 py-0.5 font-mono text-[0.875em] text-brand-700 underline decoration-brand-300 underline-offset-2 hover:bg-brand-100"
              >
                {text}
              </button>
            )
          },
        }
      : undefined
  return (
    <div className="prose prose-sm prose-slate max-w-none prose-pre:bg-slate-800 prose-pre:text-slate-100 prose-code:text-brand-700 prose-code:before:content-none prose-code:after:content-none [&_pre_code]:text-inherit">
      <ReactMarkdown
        remarkPlugins={[remarkGfm, remarkMath]}
        rehypePlugins={[[rehypeKatex, { throwOnError: false, strict: false }], rehypeHighlight]}
        components={components}
      >
        {normalizeMath(children)}
      </ReactMarkdown>
    </div>
  )
})
