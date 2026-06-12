import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Plus } from "lucide-react"
import { useState } from "react"
import { createPortal } from "react-dom"
import { nextAgentName } from "../agentConfig"
import { api } from "../api/client"
import { DEFAULT_MODEL } from "../models"
import { useStore } from "../store"
import { AccountMenu } from "./AccountMenu"

export function agentInitial(name: string): string {
  const t = name.trim()
  const m = t.match(/^([A-Za-z])[A-Za-z]*\s*(\d+)$/)
  if (m) return `${m[1].toUpperCase()}${m[2]}`
  const c = [...t][0] ?? "" // 按码点取首字:charAt 会把 emoji 等代理对劈成半个,渲染成 tofu
  return c ? c.toUpperCase() : "?"
}

const PALETTE = [
  "bg-teal-100 text-teal-700",
  "bg-violet-100 text-violet-700",
  "bg-sky-100 text-sky-700",
  "bg-amber-100 text-amber-700",
  "bg-rose-100 text-rose-700",
  "bg-emerald-100 text-emerald-700",
]
export function agentColor(name: string): string {
  let h = 0
  for (const ch of name) h = (h + (ch.codePointAt(0) ?? 0)) % 9973
  return PALETTE[h % PALETTE.length]
}

// rail tooltip:portal 到 body + fixed。头像列是滚动容器(overflow-y-auto),留在列内的
// absolute 浮层会被裁剪;portal 出去同时免疫任何祖先 filter/transform 形成的包含块陷阱
// (面板的 backdrop-blur 即此类,见 RowMenu 注释)。
function RailTip({ text, anchor }: { text: string; anchor: DOMRect }) {
  return createPortal(
    <div
      style={{ top: anchor.top + anchor.height / 2, left: anchor.right + 8 }}
      className="pointer-events-none fixed z-30 -translate-y-1/2 whitespace-nowrap rounded-md bg-slate-800 px-1.5 py-0.5 text-[11px] text-white"
    >
      {text}
    </div>,
    document.body,
  )
}

/** 左侧 46px rail:品牌方块 / agent 头像列(点选切换)/ 新建 / 账户。只管「切谁」,
 * 管理操作(改名/设置/删除)全在面板头部 AgentHeader。 */
export function AgentRail({ onCreated }: { onCreated: (id: string) => void }) {
  const userId = useStore((s) => s.userId)
  const agentId = useStore((s) => s.agentId)
  const setAgent = useStore((s) => s.setAgent)
  const qc = useQueryClient()
  const [tip, setTip] = useState<{ text: string; anchor: DOMRect } | null>(null)

  const { data: agents = [] } = useQuery({
    queryKey: ["agents", userId],
    queryFn: () => api.listAgents(),
    enabled: !!userId,
  })

  const create = useMutation({
    // 点击时刻从缓存取最新名单算默认名:闭包里的 agents 可能还是 query 解析前的空数组,
    // 会把已存在的 Agent N 重名再建一次。
    mutationFn: () => {
      const fresh = qc.getQueryData<typeof agents>(["agents", userId]) ?? agents
      return api.createAgent({
        name: nextAgentName(fresh.map((a) => a.name)),
        model: DEFAULT_MODEL,
        provider: "openai",
      })
    },
    onSuccess: async (a) => {
      await qc.invalidateQueries({ queryKey: ["agents", userId] })
      setAgent(a.id)
      onCreated(a.id) // 面板头部进入改名态(Sidebar 协调)
    },
  })

  const showTip = (text: string) => (e: React.MouseEvent<HTMLElement>) =>
    setTip({ text, anchor: e.currentTarget.getBoundingClientRect() })

  return (
    <div className="flex w-[46px] flex-none flex-col items-center gap-2 border-r border-slate-200/70 bg-slate-50 py-3">
      <span
        onMouseEnter={showTip("Agent Cloud")}
        onMouseLeave={() => setTip(null)}
        className="flex h-[30px] w-[30px] items-center justify-center rounded-[9px] bg-gradient-to-br from-brand-400 to-brand-600 text-[13px] font-bold text-white shadow-sm"
      >
        A
      </span>
      <span className="w-[22px] border-t border-slate-200" />
      {/* w-full(46px):flex 子项默认收缩到内容宽 30px,而本列 overflow-y-auto 会把 overflow-x
          一并算成 auto → ring(box-shadow)在 30px 边界被裁,选中环左右弧消失(审查 I-1)。
          py-1 给首尾头像的环留垂直余量;滚动条按 spec 隐藏。 */}
      <div className="flex min-h-0 w-full flex-1 flex-col items-center gap-2 overflow-y-auto py-1 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
        {agents.map((a) => {
          const active = a.id === agentId
          return (
            <button
              key={a.id}
              type="button"
              aria-label={a.name}
              aria-current={active || undefined}
              onMouseEnter={showTip(`${a.name} · ${a.model}`)}
              onMouseLeave={() => setTip(null)}
              onClick={() => {
                // 点已选中的 agent 不重置(setAgent 会清掉当前会话选择)
                if (a.id !== agentId) setAgent(a.id)
              }}
              className={`flex h-[30px] w-[30px] flex-none items-center justify-center rounded-full text-[11px] font-semibold transition ${agentColor(a.name)} ${
                active
                  ? "ring-2 ring-brand-500 ring-offset-1"
                  : "hover:ring-2 hover:ring-slate-300 hover:ring-offset-1"
              }`}
            >
              {agentInitial(a.name)}
            </button>
          )
        })}
      </div>
      <button
        type="button"
        aria-label="新建 Agent"
        disabled={create.isPending}
        onMouseEnter={showTip("新建 Agent")}
        onMouseLeave={() => setTip(null)}
        onClick={() => create.mutate()}
        className="flex h-[30px] w-[30px] flex-none items-center justify-center rounded-full border border-dashed border-slate-300 text-slate-400 transition hover:border-slate-400 hover:text-slate-600 disabled:opacity-50"
      >
        <Plus size={14} />
      </button>
      <AccountMenu />
      {tip && <RailTip text={tip.text} anchor={tip.anchor} />}
    </div>
  )
}
