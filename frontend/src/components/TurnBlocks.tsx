import { Bot, ChevronDown, ChevronRight } from "lucide-react"
import { useState } from "react"
import type { Block } from "../blocks"
import { stripWorkspaceImageMarkdown } from "../chatText"
import type { PathHit } from "../workspacePaths"
import { Markdown } from "./Markdown"
import { ThinkingPanel } from "./ThinkingPanel"
import { ToolCallCard } from "./ToolCallCard"
import { parseTodoItems, TodoCard } from "./TodoCard"

// 按时间顺序渲染一个回合的块流。streaming 时:最后一块若是思考则自动展开,末尾显示光标。
// resolvePath/onOpenPath:正文工作区路径 → 可点链接(由调用方注入,如 MessageList 用
// 文件索引 + 文件抽屉;不传则纯渲染,测试/其它场景零依赖)。递归子 agent 卡时原样透传。
export function TurnBlocks({
  blocks,
  streaming = false,
  resolvePath,
  onOpenPath,
  onApprove,
}: {
  blocks: Block[]
  streaming?: boolean
  resolvePath?: (text: string) => PathHit | null
  onOpenPath?: (hit: PathHit) => void
  onApprove?: (text: string) => void
}) {
  // 任务清单(todo 工具):agent 每次全量重写清单 → 多次调用只在【首现位置】渲染一张卡,
  // 内容取本组 blocks 里【最新一次】的 items(原位刷新,不逐卡罗列演进);其余 todo 块跳过。
  // 子 agent 卡内部递归调用本组件时,以其内部 blocks 为一组,天然各自独立。
  const todoBlocks = blocks.filter(
    (b): b is Extract<Block, { kind: "tool" }> =>
      b.kind === "tool" && b.call.name === "todo" && !b.progress, // 只算真卡:pending 进度卡 args 为空
  )
  const firstTodoId = todoBlocks[0]?.id
  const latestTodoItems = todoBlocks.length
    ? parseTodoItems(todoBlocks[todoBlocks.length - 1].call.arguments)
    : []
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
          return (
            <Markdown key={b.id} resolvePath={resolvePath} onOpenPath={onOpenPath}>
              {stripWorkspaceImageMarkdown(b.text)}
            </Markdown>
          )
        }
        if (b.kind === "subagent") {
          return (
            <SubagentCard
              key={b.id}
              description={b.description}
              prompt={b.prompt}
              blocks={b.blocks}
              running={b.running}
              ok={b.ok}
              resolvePath={resolvePath}
              onOpenPath={onOpenPath}
            />
          )
        }
        if (b.kind === "tool" && b.call.name === "todo") {
          // 参数生成中的 pending 进度卡照常走 ToolCallCard(此时 args 未知);升级成真卡后按上述策略渲染
          if (!b.progress && b.id !== firstTodoId) return null
          if (!b.progress) return <TodoCard key={b.id} items={latestTodoItems} />
        }
        return (
          <ToolCallCard
            key={b.id}
            call={b.call}
            result={b.result}
            progress={b.progress}
            onApprove={onApprove}
          />
        )
      })}
      {streaming && <span className="ml-0.5 animate-pulse text-brand-600">▍</span>}
    </>
  )
}

// 子 agent(task 派生)折叠卡片:运行中强制展开看进度,完成后默认折叠成一行(点头展开看过程)。
// 内部 blocks 递归用 TurnBlocks 渲染(同一渲染器,缩进在卡片体的 padding)。
function SubagentCard({
  description,
  prompt,
  blocks,
  running,
  ok,
  resolvePath,
  onOpenPath,
}: {
  description: string
  prompt: string
  blocks: Block[]
  running: boolean
  ok: boolean
  resolvePath?: (text: string) => PathHit | null
  onOpenPath?: (hit: PathHit) => void
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
          // 历史里子过程不落库 → steps=0,只显示状态图标(不显示误导的「0 步」);
          // live 完成时 steps 为真实工具数,显示「✓ N 步」。
          <span className="shrink-0 text-xs text-sky-600">
            {ok ? "✓" : "✗"}
            {steps > 0 ? ` ${steps} 步` : ""}
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
          {prompt && (
            <div className="mb-2 rounded-lg bg-sky-50 px-2.5 py-1.5 text-xs">
              <span className="font-medium text-sky-600">任务指令</span>
              <p className="mt-0.5 whitespace-pre-wrap break-words text-slate-600">{prompt}</p>
            </div>
          )}
          {/* 子 agent 内不放确认按钮(审查 M2):子 agent 是独立回合、批准码到不了它的
              user_message,按钮点了也放行不了。子 agent 被拦 = 失败汇报,主 agent 可改由
              自己直接执行(那时确认流正常生效)。与 app 端一致。 */}
          <TurnBlocks
            blocks={blocks}
            streaming={running}
            resolvePath={resolvePath}
            onOpenPath={onOpenPath}
          />
        </div>
      )}
    </div>
  )
}
