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
          return <ThinkingPanel key={b.id} text={b.text} active={streaming && i === blocks.length - 1} />
        }
        if (b.kind === "text") {
          // 剥掉指向工作区的 markdown 图(已由工具卡片展示;正文裸路径渲染会破损)
          return <Markdown key={b.id}>{stripWorkspaceImageMarkdown(b.text)}</Markdown>
        }
        return <ToolCallCard key={b.id} call={b.call} result={b.result} progress={b.progress} />
      })}
      {streaming && <span className="ml-0.5 animate-pulse text-brand-600">▍</span>}
    </>
  )
}
