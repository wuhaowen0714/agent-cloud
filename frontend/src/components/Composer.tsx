import { useQuery } from "@tanstack/react-query"
import { useEffect, useRef, useState } from "react"
import { api } from "../api/client"
import { atTokenAt, filterPaths } from "../fileRef"
import { useStore } from "../store"
import { ModelMenu } from "./model/ModelMenu"
import { matchCommands, parseInput } from "./slash/commands"
import { SlashPalette } from "./slash/SlashPalette"
import { StatusCard } from "./slash/StatusCard"
import { useSlashCommands } from "./slash/useSlashCommands"
import { Button, Textarea } from "./ui"

type Notice = { kind: "flash"; flash: string } | { kind: "status" } | { kind: "help" } | null
interface Entry {
  title: string
  hint?: string
  exec: () => void
}

export function Composer({
  disabled,
  onSend,
  onStop,
}: {
  disabled: boolean
  onSend: (text: string) => void
  onStop?: () => void
}) {
  const [text, setText] = useState("")
  const [caret, setCaret] = useState(0) // @ 文件引用按「光标所在词」判定,需跟踪 caret
  const [sel, setSel] = useState(0)
  const [dismissed, setDismissed] = useState(false) // Esc 关面板,保留文本走直通
  const [atDismissed, setAtDismissed] = useState<number | null>(null) // Esc 时 @ 词的 start;同词内不再弹
  const [notice, setNotice] = useState<Notice>(null)
  const wrapRef = useRef<HTMLDivElement>(null)
  const taRef = useRef<HTMLTextAreaElement>(null)

  const ctx = useSlashCommands({
    notify: (msg) => setNotice({ kind: "flash", flash: msg }),
    showStatus: () => setNotice({ kind: "status" }),
    showHelp: () => setNotice({ kind: "help" }),
  })

  const userId = useStore((s) => s.userId)
  const agentId = useStore((s) => s.agentId)
  // 订阅式读取(与 AgentList 共享缓存):patchAgent 失效后 chip 文本自动更新。
  const { data: agents = [] } = useQuery({
    queryKey: ["agents", userId],
    queryFn: () => api.listAgents(),
    enabled: !!userId,
  })
  const currentModel = agents.find((a) => a.id === agentId)?.model

  // @ 文件引用:光标所在 @ 词活跃才拉索引(staleTime 内打字不抖动,新文件最迟 30s 可见)。
  const atToken = atTokenAt(text, caret)
  const { data: fileIndex = [] } = useQuery({
    queryKey: ["fileIndex", userId],
    queryFn: () => api.indexFiles(),
    enabled: !!userId && !!atToken,
    staleTime: 30_000,
  })

  // 选中:把 [start, caret) 换成 "@路径 ",光标落在尾空格后(焦点保持)。
  const insertPath = (p: string) => {
    if (!atToken) return
    const next = `${text.slice(0, atToken.start)}@${p} ${text.slice(caret)}`
    const newCaret = atToken.start + p.length + 2 // "@" + 路径 + " "
    setText(next)
    setCaret(newCaret)
    setSel(0)
    requestAnimationFrame(() => {
      taRef.current?.focus()
      taRef.current?.setSelectionRange(newCaret, newCaret)
    })
  }

  // 由文本派生面板条目。@ 词活跃时文件浮层压过斜杠面板(含 /model 参数模式);
  // 无匹配则两者都不显示(正常打字),避免引用中途斜杠建议突然顶上来。
  const parsed = parseInput(text)
  const entries: Entry[] = []
  if (atToken && !disabled) {
    if (atDismissed !== atToken.start) {
      for (const p of filterPaths(fileIndex, atToken.query)) {
        entries.push({
          title: p.split("/").pop() ?? p,
          hint: p,
          exec: () => insertPath(p),
        })
      }
    }
  } else if (!dismissed && !disabled) {
    if (parsed.mode === "command") {
      for (const cmd of matchCommands(parsed.prefix)) {
        entries.push({
          title: cmd.title,
          hint: "/" + cmd.name,
          exec: () => {
            if (cmd.needsArg) {
              setText(`/${cmd.name} `)
              setSel(0)
            } else {
              void cmd.run?.(ctx)
              setText("")
            }
          },
        })
      }
    } else if (parsed.mode === "arg") {
      const { command, arg } = parsed
      const sugg = command.suggestions?.(ctx, arg) ?? []
      for (const s of sugg) {
        entries.push({
          title: s,
          hint: "模型",
          exec: () => {
            void command.runWithArg?.(ctx, s)
            setText("")
          },
        })
      }
      const trimmed = arg.trim()
      if (trimmed && !sugg.includes(trimmed)) {
        entries.push({
          title: `应用 "${trimmed}"`,
          hint: "自由输入",
          exec: () => {
            void command.runWithArg?.(ctx, trimmed)
            setText("")
          },
        })
      }
    }
  }
  const paletteOpen = entries.length > 0
  const safeSel = paletteOpen ? Math.min(sel, entries.length - 1) : 0

  // flash 自动消失;status/help 常驻直到手动关。
  useEffect(() => {
    if (notice?.kind !== "flash") return
    const t = setTimeout(() => setNotice(null), 4000)
    return () => clearTimeout(t)
  }, [notice])

  // 点 composer 外面 → 关通知卡(面板随文本变化自然收起)。
  useEffect(() => {
    if (!notice) return
    const onDoc = (e: Event) => {
      if (wrapRef.current && !wrapRef.current.contains(e.target as Node)) setNotice(null)
    }
    document.addEventListener("pointerdown", onDoc)
    return () => document.removeEventListener("pointerdown", onDoc)
  }, [notice])

  const send = () => {
    const t = text.trim()
    if (!t || disabled) return
    onSend(t)
    setText("")
  }

  return (
    <div className="border-t border-slate-200 bg-white/80 p-3 backdrop-blur">
      <div className="mx-auto max-w-5xl">
      <div ref={wrapRef} className="relative flex items-end gap-2">
        {notice && (
          <StatusCard
            kind={notice.kind}
            status={notice.kind === "status" ? ctx.status() : undefined}
            flash={notice.kind === "flash" ? notice.flash : undefined}
            onClose={() => setNotice(null)}
          />
        )}
        {paletteOpen && (
          <SlashPalette
            items={entries.map((e) => ({ title: e.title, hint: e.hint }))}
            selectedIndex={safeSel}
            onSelect={(i) => entries[i]?.exec()}
            onHover={(i) => setSel(i)}
          />
        )}
        <Textarea
          ref={taRef}
          className="min-h-[44px] flex-1"
          placeholder={disabled ? "生成中…" : "说点什么(/ 命令,@ 引用文件,Enter 发送)"}
          rows={1}
          value={text}
          disabled={disabled}
          onChange={(e) => {
            const v = e.target.value
            const c = e.target.selectionStart ?? v.length
            setText(v)
            setCaret(c)
            setSel(0)
            setDismissed(false)
            // @ 词消失或换位 → 解除 Esc 豁免(同词内继续打字保持关闭)
            if (atDismissed !== null && atTokenAt(v, c)?.start !== atDismissed) setAtDismissed(null)
          }}
          onSelect={(e) => setCaret(e.currentTarget.selectionStart ?? 0)}
          onKeyDown={(e) => {
            // IME 组词中的回车(选字)不应触发命令执行/发送。
            if (e.nativeEvent.isComposing) return
            if (paletteOpen) {
              if (e.key === "ArrowDown") {
                e.preventDefault()
                setSel((i) => Math.min(i + 1, entries.length - 1))
              } else if (e.key === "ArrowUp") {
                e.preventDefault()
                setSel((i) => Math.max(i - 1, 0))
              } else if (e.key === "Enter" || e.key === "Tab") {
                e.preventDefault()
                entries[safeSel]?.exec()
              } else if (e.key === "Escape") {
                e.preventDefault()
                if (atToken) setAtDismissed(atToken.start)
                else setDismissed(true)
                setNotice(null) // 一并收起通知卡(若有)
              }
              return
            }
            if (e.key === "Escape" && notice) {
              e.preventDefault()
              setNotice(null)
            } else if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault()
              send()
            }
          }}
        />
        {disabled && onStop ? (
          <Button variant="secondary" className="h-11" onClick={onStop}>
            停止
          </Button>
        ) : (
          <Button className="h-11" disabled={disabled} onClick={send}>
            发送
          </Button>
        )}
      </div>
      {/* 左下模型 chip(仿 Claude Code):即点即切,持久到当前 agent(与 /model 同语义)。
          streaming 中跟随输入区一起禁用;失败走 flash 反馈(与斜杠路径对齐)。 */}
      {agentId && currentModel && (
        <div className={`mt-1.5 flex items-center ${disabled ? "pointer-events-none opacity-50" : ""}`}>
          <ModelMenu
            variant="chip"
            value={currentModel}
            onChange={(m) => void ctx.setModel(m).catch(() => ctx.notify("切换模型失败"))}
          />
        </div>
      )}
      </div>
    </div>
  )
}
