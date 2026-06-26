import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { act, fireEvent, render, screen } from "@testing-library/react"
import { afterEach, describe, expect, it, vi } from "vitest"
import { api, HttpError } from "../api/client"
import { useStore } from "../store"
import { Composer } from "./Composer"

const USER = "u1"

const AGENTS = [
  { id: "a1", name: "Coder", enabled_tools: [], permissions: {} },
  { id: "a2", name: "Other", enabled_tools: [], permissions: {} },
]

const SESSIONS = [
  {
    id: "s1",
    user_id: USER,
    agent_config_id: "a1",
    model: "gpt-4o", // 模型在 session 级(图一 chip / /model / status 都读它)
    credential_id: null,
    title: "T",
    work_subdir: "workspace",
    last_active_at: "2026-06-12T12:00:00Z",
    last_context_tokens: 873,
  },
]

const FILE_INDEX = ["src/app.py", "docs/读我.md", "README.md"]

function setup(opts?: { disabled?: boolean; visionModels?: string[] }) {
  const qc = new QueryClient()
  useStore.setState({ userId: USER, agentId: "a1", sessionId: "s1" })
  qc.setQueryData(["agents", USER], AGENTS)
  // 挂载即后台 refetch:mock 回同一数组防覆盖空(chip flaky)。模型选单走 platform + credentials。
  vi.spyOn(api, "listAgents").mockResolvedValue(AGENTS as never)
  vi.spyOn(api, "listSessions").mockResolvedValue(SESSIONS as never)
  vi.spyOn(api, "getPlatformModels").mockResolvedValue({
    models: ["DeepSeek-V4-Pro", "DeepSeek-V4-Flash", "gpt-4o"],
    default: "DeepSeek-V4-Pro",
    vision_models: opts?.visionModels ?? ["gpt-4o"], // 默认 gpt-4o 是 vision;路由测试可覆盖为 []
  })
  vi.spyOn(api, "listCredentials").mockResolvedValue([])
  vi.spyOn(api, "indexFiles").mockResolvedValue(FILE_INDEX)
  qc.setQueryData(["sessions", USER], SESSIONS)
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
  useStore.setState({
    userId: null,
    agentId: null,
    sessionId: null,
    live: null,
    compactions: {},
    composerDraft: null,
    pendingSkill: null,
    settingsOpen: false,
  })
  vi.restoreAllMocks()
})

describe("Composer 回填(composerDraft)", () => {
  it("composerDraft 非空 → 写入输入框并清空(消费一次)", () => {
    setup()
    act(() => {
      useStore.getState().setComposerDraft("回填的问题")
    })
    expect(box()).toHaveValue("回填的问题")
    expect(useStore.getState().composerDraft).toBeNull()
  })
})

describe("Composer 基础", () => {
  it("idle 显示发送并回调 onSend", () => {
    const { onSend } = setup()
    type("hi")
    fireEvent.click(screen.getByText("发送"))
    expect(onSend).toHaveBeenCalledWith("hi", [])
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

  it("/model → 参数模式列建议 → 选中调 patchSession(session 级)", async () => {
    const spy = vi.spyOn(api, "patchSession").mockResolvedValue({} as never)
    setup()
    type("/model")
    fireEvent.keyDown(box(), { key: "Enter" }) // 进参数模式,text → "/model "
    expect(box()).toHaveValue("/model ")
    expect(await screen.findByRole("option", { name: /DeepSeek-V4-Flash/ })).toBeInTheDocument()
    // 用 option 角色定位面板建议项(底部模型 chip 也含 "gpt-4o" 文本,纯文本定位会歧义)
    const opt = await screen.findByRole("option", { name: /gpt-4o/ })
    fireEvent.mouseDown(opt)
    expect(spy).toHaveBeenCalledWith("s1", { model: "gpt-4o" })
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
    expect(onSend).toHaveBeenCalledWith("/usr/bin/python", [])
  })

  it("Esc 关面板后 Enter → 直通发送", () => {
    const { onSend } = setup()
    type("/status")
    expect(screen.getByRole("listbox")).toBeInTheDocument()
    fireEvent.keyDown(box(), { key: "Escape" })
    expect(screen.queryByRole("listbox")).not.toBeInTheDocument()
    fireEvent.keyDown(box(), { key: "Enter" })
    expect(onSend).toHaveBeenCalledWith("/status", [])
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

describe("压缩反馈(per-session)", () => {
  // 受控 promise:压缩挂起在"运行中",由测试决定何时完成。
  const deferredCompact = () => {
    let resolve!: (v: { compacted: boolean }) => void
    vi.spyOn(api, "compactSession").mockReturnValue(new Promise((r) => (resolve = r)))
    return () => resolve({ compacted: true })
  }

  it("运行中显示『正在压缩上下文…』并禁用输入,完成后弹结果并恢复", async () => {
    const finish = deferredCompact()
    setup()
    type("/compact")
    fireEvent.keyDown(box(), { key: "Enter" })
    expect(await screen.findByText("正在压缩上下文…")).toBeInTheDocument()
    expect(box()).toBeDisabled()
    await act(async () => {
      finish()
    })
    expect(await screen.findByText("已压缩当前会话上下文")).toBeInTheDocument()
    expect(screen.queryByText("正在压缩上下文…")).not.toBeInTheDocument()
    expect(box()).not.toBeDisabled()
  })

  it("不串台:A 压缩中切到 B → B 无提示且可输入;A 完成时在 B 不弹;切回 A 才弹结果", async () => {
    const finish = deferredCompact()
    setup() // sessionId = "s1"
    type("/compact")
    fireEvent.keyDown(box(), { key: "Enter" })
    await screen.findByText("正在压缩上下文…")

    // 压缩进行中切到别的会话 s2
    act(() => {
      useStore.setState({ sessionId: "s2" })
    })
    expect(screen.queryByText("正在压缩上下文…")).not.toBeInTheDocument()
    expect(box()).not.toBeDisabled()

    // s1 的压缩此刻完成(用户正看 s2)→ s2 绝不弹任何压缩提示
    await act(async () => {
      finish()
    })
    expect(screen.queryByText("已压缩当前会话上下文")).not.toBeInTheDocument()

    // 切回 s1 → 才看到结果
    act(() => {
      useStore.setState({ sessionId: "s1" })
    })
    expect(await screen.findByText("已压缩当前会话上下文")).toBeInTheDocument()
  })

  it("结果 flash 不滞留到别的会话:A 显示后切到 B 立即消失", async () => {
    vi.spyOn(api, "compactSession").mockResolvedValue({ compacted: true })
    setup() // sessionId = "s1"
    type("/compact")
    fireEvent.keyDown(box(), { key: "Enter" })
    expect(await screen.findByText("已压缩当前会话上下文")).toBeInTheDocument()
    act(() => {
      useStore.setState({ sessionId: "s2" })
    })
    expect(screen.queryByText("已压缩当前会话上下文")).not.toBeInTheDocument()
  })
})

describe("@ 文件引用", () => {
  it("@ 弹出文件浮层:title=文件名,hint=完整路径", async () => {
    setup()
    type("@")
    expect(await screen.findByRole("option", { name: /app\.py.*src\/app\.py/ })).toBeInTheDocument()
    expect(screen.getByRole("option", { name: /读我\.md/ })).toBeInTheDocument()
    expect(screen.getByRole("option", { name: /README\.md/ })).toBeInTheDocument()
  })

  it("@读 过滤到中文命中项", async () => {
    setup()
    type("@")
    await screen.findByRole("option", { name: /app\.py/ })
    type("@读")
    expect(screen.queryByRole("option", { name: /app\.py/ })).not.toBeInTheDocument()
    expect(screen.getByRole("option", { name: /读我\.md/ })).toBeInTheDocument()
  })

  it("Enter 选中 → 替换 @词为 @完整路径 + 空格", async () => {
    setup()
    type("看下 @app")
    await screen.findByRole("option", { name: /app\.py/ })
    fireEvent.keyDown(box(), { key: "Enter" })
    expect(box()).toHaveValue("看下 @src/app.py ")
    expect(screen.queryByRole("listbox")).not.toBeInTheDocument()
  })

  it("鼠标点选插入路径", async () => {
    setup()
    type("@")
    const opt = await screen.findByRole("option", { name: /README/ })
    fireEvent.mouseDown(opt)
    expect(box()).toHaveValue("@README.md ")
  })

  it("Esc 关浮层,同一 @ 词内不再弹;清空后新 @ 再弹", async () => {
    setup()
    type("@a")
    await screen.findByRole("listbox")
    fireEvent.keyDown(box(), { key: "Escape" })
    expect(screen.queryByRole("listbox")).not.toBeInTheDocument()
    type("@ap") // 同词(start=0)继续打字 → 仍不弹
    expect(screen.queryByRole("listbox")).not.toBeInTheDocument()
    type("") // 删光:@ 词消失,豁免解除
    type("@")
    expect(await screen.findByRole("listbox")).toBeInTheDocument()
  })

  it("@ 词活跃时压过斜杠面板(/model 参数模式)", async () => {
    setup()
    type("/model @")
    expect(await screen.findByRole("option", { name: /app\.py/ })).toBeInTheDocument()
    expect(screen.queryByRole("option", { name: /DeepSeek-V4-Flash/ })).not.toBeInTheDocument()
  })

  it("无匹配 query → 无浮层,Enter 直通发送", async () => {
    const { onSend } = setup()
    type("@")
    await screen.findByRole("listbox") // 先等索引到位(缓存)
    type("@zzz")
    expect(screen.queryByRole("listbox")).not.toBeInTheDocument()
    fireEvent.keyDown(box(), { key: "Enter" })
    expect(onSend).toHaveBeenCalledWith("@zzz", [])
  })

  it("邮箱不触发浮层", () => {
    setup()
    type("发邮件给 a@b.com")
    expect(screen.queryByRole("listbox")).not.toBeInTheDocument()
  })

  it("IME 组词回车不选中", async () => {
    const { onSend } = setup()
    type("@")
    await screen.findByRole("listbox")
    fireEvent.keyDown(box(), { key: "Enter", isComposing: true })
    expect(onSend).not.toHaveBeenCalled()
    expect(box()).toHaveValue("@")
  })

  it("发送后 Esc 豁免重置:新消息开头的 @ 正常弹层(审查 M1)", async () => {
    const { onSend } = setup()
    type("@a")
    await screen.findByRole("listbox")
    fireEvent.keyDown(box(), { key: "Escape" }) // 豁免 start=0
    fireEvent.keyDown(box(), { key: "Enter" }) // 直通发送 "@a"
    expect(onSend).toHaveBeenCalledWith("@a", [])
    type("@") // 新消息开头同样 start=0,不应被旧豁免压住
    expect(await screen.findByRole("listbox")).toBeInTheDocument()
  })

  it("索引加载中:显示占位,Enter 不直通发送(审查 L1)", async () => {
    const { onSend } = setup()
    let resolve!: (v: string[]) => void
    vi.spyOn(api, "indexFiles").mockImplementation(
      () => new Promise<string[]>((r) => (resolve = r)),
    )
    type("@app")
    expect(await screen.findByText("加载文件索引…")).toBeInTheDocument()
    fireEvent.keyDown(box(), { key: "Enter" })
    expect(onSend).not.toHaveBeenCalled()
    resolve(FILE_INDEX)
    expect(await screen.findByRole("option", { name: /app\.py/ })).toBeInTheDocument()
  })

  it("索引加载失败:显示失败提示而非静默(审查 L1)", async () => {
    setup()
    vi.spyOn(api, "indexFiles").mockRejectedValue(new Error("net"))
    type("@")
    expect(await screen.findByText("文件索引加载失败", undefined, { timeout: 4000 })).toBeInTheDocument()
  })
})

describe("模型 chip(session 级 · provider+model 两栏)", () => {
  it("点 model 栏切换 → 写当前 session(patchSession)", async () => {
    const spy = vi.spyOn(api, "patchSession").mockResolvedValue({} as never)
    setup()
    fireEvent.click(screen.getByRole("button", { name: "model" }))
    fireEvent.click(await screen.findByRole("option", { name: /DeepSeek-V4-Flash/ }))
    expect(spy).toHaveBeenCalledWith("s1", {
      model: "DeepSeek-V4-Flash",
      credential_id: null,
    })
  })

  it("切换失败 → flash 提示(不静默)", async () => {
    vi.spyOn(api, "patchSession").mockRejectedValue(new Error("net"))
    setup()
    fireEvent.click(screen.getByRole("button", { name: "model" }))
    fireEvent.click(await screen.findByRole("option", { name: /DeepSeek-V4-Flash/ }))
    expect(await screen.findByText("切换模型失败")).toBeInTheDocument()
  })
})

describe("图片上传(附件)", () => {
  const fileInput = () => document.querySelector('input[type="file"]') as HTMLInputElement
  const pick = async (name = "cat.png") => {
    const file = new File(["x"], name, { type: "image/png" })
    await act(async () => {
      fireEvent.change(fileInput(), { target: { files: [file] } })
    })
  }

  it("上传后发送:消息末尾带工作区路径", async () => {
    vi.spyOn(api, "uploadFiles").mockResolvedValue([
      { name: "cat.png", path: "upload/cat.png", size: 10, is_dir: false },
    ] as never)
    vi.spyOn(api, "previewUrl").mockResolvedValue("blob:fake")
    const { onSend } = setup()
    await pick()
    expect(await screen.findByAltText("cat.png")).toBeInTheDocument()
    expect(api.uploadFiles).toHaveBeenCalledWith("upload", [expect.any(File)])
    type("把背景换成沙滩")
    fireEvent.click(screen.getByText("发送"))
    const sent = (onSend as ReturnType<typeof vi.fn>).mock.calls[0][0] as string
    expect(sent).toContain("把背景换成沙滩")
    expect(sent).toContain("upload/cat.png")
  })

  it("上传失败 → flash 提示", async () => {
    vi.spyOn(api, "uploadFiles").mockRejectedValue(new Error("net"))
    setup()
    await pick()
    expect(await screen.findByText("文件上传失败")).toBeInTheDocument()
  })

  it("可移除已上传的附件", async () => {
    vi.spyOn(api, "uploadFiles").mockResolvedValue([
      { name: "cat.png", path: "upload/cat.png", size: 10, is_dir: false },
    ] as never)
    vi.spyOn(api, "previewUrl").mockResolvedValue("blob:fake")
    setup()
    await pick()
    expect(await screen.findByAltText("cat.png")).toBeInTheDocument()
    fireEvent.click(screen.getByLabelText("移除附件"))
    expect(screen.queryByAltText("cat.png")).not.toBeInTheDocument()
  })

  it("仅附件、无文本也能发送(消息只含路径)", async () => {
    vi.spyOn(api, "uploadFiles").mockResolvedValue([
      { name: "cat.png", path: "upload/cat.png", size: 10, is_dir: false },
    ] as never)
    vi.spyOn(api, "previewUrl").mockResolvedValue("blob:fake")
    const { onSend } = setup()
    await pick()
    await screen.findByAltText("cat.png")
    fireEvent.click(screen.getByText("发送")) // 不打字
    const sent = (onSend as ReturnType<typeof vi.fn>).mock.calls[0][0] as string
    expect(sent).toContain("upload/cat.png")
  })

  it("带图但没有任何 vision 模型可用 → 提示,不发送", async () => {
    vi.spyOn(api, "uploadFiles").mockResolvedValue([
      { name: "cat.png", path: "upload/cat.png", size: 10, is_dir: false },
    ] as never)
    vi.spyOn(api, "previewUrl").mockResolvedValue("blob:fake")
    const { onSend } = setup({ visionModels: [] }) // 平台无 vision 模型,无处可切
    await pick()
    await screen.findByAltText("cat.png")
    fireEvent.click(screen.getByText("发送"))
    expect(onSend).not.toHaveBeenCalled() // 无 vision 可切 → 拦下不发
    expect(await screen.findByText(/没有支持图片的模型/)).toBeInTheDocument()
  })

  it("带图但当前模型不支持 → 自动切到 vision 模型并发送", async () => {
    vi.spyOn(api, "uploadFiles").mockResolvedValue([
      { name: "cat.png", path: "upload/cat.png", size: 10, is_dir: false },
    ] as never)
    vi.spyOn(api, "previewUrl").mockResolvedValue("blob:fake")
    const patch = vi.spyOn(api, "patchSession").mockResolvedValue({} as never)
    // 当前 session 模型 gpt-4o 不在 vision 列表;平台有 vision 模型 DeepSeek-V4-Flash 可切。
    const { onSend } = setup({ visionModels: ["DeepSeek-V4-Flash"] })
    await pick()
    await screen.findByAltText("cat.png")
    fireEvent.click(screen.getByText("发送"))
    // 自动 PATCH 切到 vision 模型,提示已切换,并照常发送(带图)
    expect(await screen.findByText(/已自动切换/)).toBeInTheDocument()
    expect(patch).toHaveBeenCalledWith("s1", {
      model: "DeepSeek-V4-Flash",
      credential_id: null,
    })
    expect(onSend).toHaveBeenCalled()
  })

  it("拖拽任意文件到输入区上传(非图也行,路径在 upload/)", async () => {
    vi.spyOn(api, "uploadFiles").mockResolvedValue([
      { name: "notes.txt", path: "upload/notes.txt", size: 5, is_dir: false },
    ] as never)
    setup()
    const file = new File(["hi"], "notes.txt", { type: "text/plain" })
    const dropZone = screen.getByTestId("composer-dropzone")
    await act(async () => {
      fireEvent.drop(dropZone, { dataTransfer: { files: [file] } })
    })
    expect(await screen.findByText("notes.txt")).toBeInTheDocument()
    expect(api.uploadFiles).toHaveBeenCalledWith("upload", [expect.any(File)])
  })
})

describe("技能选用(chip)", () => {
  it("setPendingSkill(/skills 选中)→ 显示 skill chip", async () => {
    setup()
    act(() => {
      useStore.getState().setPendingSkill("文档整理")
    })
    expect(await screen.findByText("文档整理")).toBeInTheDocument()
  })

  it("发送:技能随消息带上 [请使用技能:X],并清空 chip", async () => {
    const { onSend } = setup()
    act(() => {
      useStore.getState().setPendingSkill("文档整理")
    })
    await screen.findByText("文档整理")
    type("帮我整理这些")
    fireEvent.click(screen.getByText("发送"))
    const sent = (onSend as ReturnType<typeof vi.fn>).mock.calls[0][0] as string
    expect(sent).toContain("帮我整理这些")
    expect(sent).toContain("[请使用技能:文档整理]")
    expect(screen.queryByText("文档整理")).not.toBeInTheDocument()
  })

  it("可移除 skill chip", async () => {
    setup()
    act(() => {
      useStore.getState().setPendingSkill("brainstorm")
    })
    await screen.findByText("brainstorm")
    fireEvent.click(screen.getByLabelText("移除技能"))
    expect(screen.queryByText("brainstorm")).not.toBeInTheDocument()
  })

  it("仅技能、无正文无附件:提示补充需求,不发送(对抗审查 M2)", async () => {
    const { onSend } = setup()
    act(() => {
      useStore.getState().setPendingSkill("brainstorm")
    })
    await screen.findByText("brainstorm")
    fireEvent.click(screen.getByText("发送"))
    expect(onSend).not.toHaveBeenCalled()
    expect(await screen.findByText("补充需求后再发送")).toBeInTheDocument()
  })
})
