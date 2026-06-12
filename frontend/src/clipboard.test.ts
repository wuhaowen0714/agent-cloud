import { afterEach, describe, expect, it, vi } from "vitest"
import { copyText } from "./clipboard"

// jsdom 没有 navigator.clipboard 和 document.execCommand,逐测试显式装/卸。
const setClipboard = (v: unknown) => Object.assign(navigator, { clipboard: v })

afterEach(() => {
  setClipboard(undefined)
  // @ts-expect-error 清掉测试装上的 execCommand mock
  delete document.execCommand
  vi.restoreAllMocks()
})

describe("copyText", () => {
  it("clipboard API 可用 → writeText,不走 execCommand", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined)
    setClipboard({ writeText })
    document.execCommand = vi.fn(() => true)
    expect(await copyText("hi")).toBe(true)
    expect(writeText).toHaveBeenCalledWith("hi")
    expect(document.execCommand).not.toHaveBeenCalled()
  })

  it("clipboard 为 undefined(HTTP 公网部署)→ 退回 execCommand 且复制的是原文本", async () => {
    setClipboard(undefined)
    let copiedValue: string | null = null
    let focusedAtExec = false
    document.execCommand = vi.fn((cmd: string) => {
      // exec 时刻临时 textarea 必须在 DOM 里、持有焦点(Firefox 取焦点处选区)且装着待复制文本
      const ta = document.querySelector("textarea")
      copiedValue = ta?.value ?? null
      focusedAtExec = document.activeElement === ta
      return cmd === "copy"
    })
    expect(await copyText("http 下也要能复制")).toBe(true)
    expect(document.execCommand).toHaveBeenCalledWith("copy")
    expect(copiedValue).toBe("http 下也要能复制")
    expect(focusedAtExec).toBe(true)
    expect(document.querySelector("textarea")).toBeNull() // 用完即删
  })

  it("fallback 完成后恢复原焦点(不打断正在输入框打字的人)", async () => {
    setClipboard(undefined)
    document.execCommand = vi.fn(() => true)
    const input = document.createElement("input")
    document.body.appendChild(input)
    input.focus()
    await copyText("x")
    expect(document.activeElement).toBe(input)
    input.remove()
  })

  it("writeText 被拒(权限)→ 退回 execCommand", async () => {
    setClipboard({ writeText: vi.fn().mockRejectedValue(new Error("denied")) })
    document.execCommand = vi.fn(() => true)
    expect(await copyText("hi")).toBe(true)
    expect(document.execCommand).toHaveBeenCalledWith("copy")
  })

  it("两条路都不通 → false(execCommand 返回 false 或抛异常)", async () => {
    setClipboard(undefined)
    document.execCommand = vi.fn(() => false)
    expect(await copyText("hi")).toBe(false)
    document.execCommand = vi.fn(() => {
      throw new Error("unsupported")
    })
    expect(await copyText("hi")).toBe(false)
    expect(document.querySelector("textarea")).toBeNull() // 异常路径也要清理
  })
})
