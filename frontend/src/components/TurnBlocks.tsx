import { Bot, ChevronDown, ChevronRight } from "lucide-react"
import { useState } from "react"
import type { Block } from "../blocks"
import { stripWorkspaceImageMarkdown } from "../chatText"
import { Markdown } from "./Markdown"
import { ThinkingPanel } from "./ThinkingPanel"
import { ToolCallCard } from "./ToolCallCard"

// 按时间顺序渲染一个回合的块流。streaming 时:最后一块若是思考则自动展开,末尾显示光标。
export function TurnBlocks({ blocks, streaming = false }: { blocks: Block[]; streaming?: boolean }) {
  return (
    <>
      {blocks.map((b, i) => {
        if (b.kind === "thinking") {
          return (
            <ThinkingPanel key={b.id} text={b.text} active={streaming && i === blocks.length - 1} />
          )
        }
        if (b.kind === "text") {
          // 剥掉指向工作区的 markdown 图(已由工具卡片展示;正文裸路径渲染会破损)
          return <Markdown key={b.id}>{stripWorkspaceImageMarkdown(b.text)}</Markdown>
        }
        if (b.kind === "subagent") {
          return (
            <SubagentCard
              key={b.id}
              description={b.description}
              blocks={b.blocks}
              running={b.running}
              ok={b.ok}
            />
          )
        }
        return <ToolCallCard key={b.id} call={b.call} result={b.result} progress={b.progress} />
      })}
      {streaming && <span className="ml-0.5 animate-pulse text-brand-600">▍</span>}
    </>
  )
}

// 子 agent(task 派生)折叠卡片:运行中强制展开看进度,完成后默认折叠成一行(点头展开看过程)。
// 内部 blocks 递归用 TurnBlocks 渲染(同一渲染器,缩进在卡片体的 padding)。
function SubagentCard({
  description,
  blocks,
  running,
  ok,
}: {
  description: string
  blocks: Block[]
  running: boolean
  ok: boolean
}) {
  const [open, setOpen] = useState(false)
  const expanded = running || open // 运行中强制展开;完成后默认折叠
  const steps = blocks.filter((b) => b.kind === "tool").length
  return (
    <div className="my-1.5 overflow-hidden rounded-xl border border-sky-200 bg-sky-50/60">
      <button
        type="button"
        onClick={() => !running && setOpen((v) => !v)}
        disabled={running}
        aria-expanded={expanded}
        className="flex w-full items-center gap-2 px-3 py-2 text-left text-sm text-sky-800 disabled:cursor-default"
      >
        <Bot size={15} className="shrink-0 text-sky-600" aria-hidden />
        <span className="shrink-0 font-medium">子 agent</span>
        <span className="min-w-0 flex-1 truncate text-sky-700">· {description}</span>
        {running ? (
          <span className="shrink-0 text-xs text-sky-600">运行中…</span>
        ) : (
          <span className="shrink-0 text-xs text-sky-600">
            {ok ? "✓" : "✗"} {steps} 步
          </span>
        )}
        {!running &&
          (expanded ? (
            <ChevronDown size={14} className="shrink-0 text-sky-500" aria-hidden />
          ) : (
            <ChevronRight size={14} className="shrink-0 text-sky-500" aria-hidden />
          ))}
      </button>
      {expanded && (
        <div className="border-t border-sky-100 bg-white px-3 py-2">
          <TurnBlocks blocks={blocks} streaming={running} />
        </div>
      )}
    </div>
  )
}
