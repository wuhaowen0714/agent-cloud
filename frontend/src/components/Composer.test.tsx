import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { fireEvent, render, screen } from "@testing-library/react"
import { afterEach, describe, expect, it, vi } from "vitest"
import { api, HttpError } from "../api/client"
import { useStore } from "../store"
import { Composer } from "./Composer"

const USER = "u1"

const AGENTS = [
  {
    id: "a1",
    name: "Coder",
    model: "gpt-4o",
    provider: "openai",
    thinking_level: null,
    enabled_tools: [],
    permissions: {},
    key_ref: null,
  },
  {
    id: "a2",
    name: "Other",
    model: "claude-x",
    provider: "anthropic",
    thinking_level: null,
    enabled_tools: [],
    permissions: {},
    key_ref: null,
  },
]

function setup(opts?: { disabled?: boolean }) {
  const qc = new QueryClient()
  useStore.setState({ userId: USER, agentId: "a1", sessionId: "s1" })
  qc.setQueryData(["agents", USER], AGENTS)
  // Composer 的 useQuery(["agents"]) 挂载即后台 refetch:mock 必须回同一数组,
  // 否则会把预填缓存覆盖空、chip 消失(flaky)。userModels 同理 mock 防真网络。
  vi.spyOn(api, "listAgents").mockResolvedValue(AGENTS as never)
  vi.spyOn(api, "listModels").mockResolvedValue([])
  qc.setQueryData(
    ["sessions", USER],
    [
      {
        id: "s1",
        user_id: USER,
        agent_config_id: "a1",
        title: "T",
        work_subdir: "workspace",
        last_context_tokens: 873,
      },
    ],
  )
  qc.setQueryData(["messages", "s1"], [{ id: "m1" }, { id: "m2" }, { id: "m3" }])
  const onSend = vi.fn()
  render(
    <QueryClientProvider client={qc}>
      <Composer disabled={opts?.disabled ?? false} onSend={onSend} onStop={() => {}} />
    </QueryClientProvider>,
  )
  return { onSend }
}

const box = () => screen.getByRole("textbox")
const type = (v: string) => fireEvent.change(box(), { target: { value: v } })

afterEach(() => {
  useStore.setState({ userId: null, agentId: null, sessionId: null, settingsOpen: false })
  vi.restoreAllMocks()
})

describe("Composer 基础", () => {
  it("idle 显示发送并回调 onSend", () => {
    const { onSend } = setup()
    type("hi")
    fireEvent.click(screen.getByText("发送"))
    expect(onSend).toHaveBeenCalledWith("hi")
  })
  it("streaming 显示停止", () => {
    setup({ disabled: true })
    expect(screen.queryByText("发送")).not.toBeInTheDocument()
    expect(screen.getByText("停止")).toBeInTheDocument()
  })
})

describe("斜杠面板", () => {
  it("输入 / 列出全部命令;/co 只剩 compact", () => {
    setup()
    type("/")
    expect(screen.getByText("压缩上下文")).toBeInTheDocument()
    expect(screen.getByText("切换模型")).toBeInTheDocument()
    type("/co")
    expect(screen.getByText("压缩上下文")).toBeInTheDocument()
    expect(screen.queryByText("切换模型")).not.toBeInTheDocument()
  })

  it("↑↓ 改变高亮", () => {
    setup()
    type("/")
    expect(screen.getAllByRole("option")[0]).toHaveAttribute("aria-selected", "true")
    fireEvent.keyDown(box(), { key: "ArrowDown" })
    expect(screen.getAllByRole("option")[1]).toHaveAttribute("aria-selected", "true")
  })

  it("/compact Enter → 调 compactSession 并 flash", async () => {
    const spy = vi.spyOn(api, "compactSession").mockResolvedValue({ compacted: true })
    setup()
    type("/compact")
    fireEvent.keyDown(box(), { key: "Enter" })
    expect(spy).toHaveBeenCalledWith("s1")
    expect(await screen.findByText("已压缩当前会话上下文")).toBeInTheDocument()
  })

  it("/model → 参数模式列建议 → 选中调 patchAgent", async () => {
    const spy = vi.spyOn(api, "patchAgent").mockResolvedValue({} as never)
    setup()
    type("/model")
    fireEvent.keyDown(box(), { key: "Enter" }) // 进参数模式,text → "/model "
    expect(box()).toHaveValue("/model ")
    expect(await screen.findByRole("option", { name: /DeepSeek-V4-Flash/ })).toBeInTheDocument() // 预设进入建议
    // 用 option 角色定位面板建议项(底部模型 chip 也含 "gpt-4o" 文本,纯文本定位会歧义)
    const opt = await screen.findByRole("option", { name: /gpt-4o/ })
    fireEvent.mouseDown(opt)
    expect(spy).toHaveBeenCalledWith("a1", { model: "gpt-4o" })
  })

  it("/new Enter → 调 createSession", () => {
    const spy = vi.spyOn(api, "createSession").mockResolvedValue({ id: "s2" } as never)
    setup()
    type("/new")
    fireEvent.keyDown(box(), { key: "Enter" })
    expect(spy).toHaveBeenCalledWith({ agent_config_id: "a1" })
  })

  it("/memory Enter → 打开记忆设置", () => {
    setup()
    type("/memory")
    fireEvent.keyDown(box(), { key: "Enter" })
    expect(useStore.getState().settingsOpen).toBe(true)
    expect(useStore.getState().settingsTab).toBe("memory")
  })

  it("/status Enter → 状态卡显示 agent/模型", async () => {
    setup()
    type("/status")
    fireEvent.keyDown(box(), { key: "Enter" })
    expect(await screen.findByText("Coder")).toBeInTheDocument()
    // 状态卡「模型」行的值(chip 也含 "gpt-4o" 文本,改按 dt→dd 结构断言)
    expect(screen.getByText("模型").nextElementSibling?.textContent).toBe("gpt-4o")
    expect(screen.getByText("873 tokens")).toBeInTheDocument()
  })

  it("无匹配 / 路径样输入 → 直通发送", () => {
    const { onSend } = setup()
    type("/usr/bin/python")
    expect(screen.queryByRole("listbox")).not.toBeInTheDocument()
    fireEvent.keyDown(box(), { key: "Enter" })
    expect(onSend).toHaveBeenCalledWith("/usr/bin/python")
  })

  it("Esc 关面板后 Enter → 直通发送", () => {
    const { onSend } = setup()
    type("/status")
    expect(screen.getByRole("listbox")).toBeInTheDocument()
    fireEvent.keyDown(box(), { key: "Escape" })
    expect(screen.queryByRole("listbox")).not.toBeInTheDocument()
    fireEvent.keyDown(box(), { key: "Enter" })
    expect(onSend).toHaveBeenCalledWith("/status")
  })

  it("无 agent 时 /new 不建会话且如实反馈(不谎报成功)", async () => {
    setup()
    useStore.setState({ agentId: null })
    const spy = vi.spyOn(api, "createSession")
    type("/new")
    fireEvent.keyDown(box(), { key: "Enter" })
    expect(spy).not.toHaveBeenCalled()
    expect(await screen.findByText("请先选择一个 agent")).toBeInTheDocument()
  })

  it("/compact 撞 409 → 提示会话正忙(而非泛化失败)", async () => {
    vi.spyOn(api, "compactSession").mockRejectedValue(new HttpError(409, "busy"))
    setup()
    type("/compact")
    fireEvent.keyDown(box(), { key: "Enter" })
    expect(await screen.findByText("会话正忙(回合进行中),稍后再试")).toBeInTheDocument()
  })
})

describe("模型 chip", () => {
  it("显示当前 agent 模型,选单切换调 patchAgent", async () => {
    const spy = vi.spyOn(api, "patchAgent").mockResolvedValue({} as never)
    setup()
    const chip = screen.getByRole("button", { name: /gpt-4o/ })
    fireEvent.click(chip)
    fireEvent.click(await screen.findByRole("option", { name: /DeepSeek-V4-Flash/ }))
    expect(spy).toHaveBeenCalledWith("a1", { model: "DeepSeek-V4-Flash" })
  })

  it("切换失败 → flash 提示(不静默)", async () => {
    vi.spyOn(api, "patchAgent").mockRejectedValue(new Error("net"))
    setup()
    fireEvent.click(screen.getByRole("button", { name: /gpt-4o/ }))
    fireEvent.click(await screen.findByRole("option", { name: /GLM-5\.1/ }))
    expect(await screen.findByText("切换模型失败")).toBeInTheDocument()
  })
})
