import { describe, expect, it } from "vitest"
import { COMMANDS, matchCommands, parseInput } from "./commands"

describe("parseInput", () => {
  it("命令模式:斜杠 + 前缀", () => {
    expect(parseInput("/")).toEqual({ mode: "command", prefix: "" })
    expect(parseInput("/co")).toEqual({ mode: "command", prefix: "co" })
  })
  it("匹配不到前缀 → none", () => {
    expect(parseInput("/zzz")).toEqual({ mode: "none" })
  })
  it("路径样输入(斜杠后含斜杠)→ none(直通)", () => {
    expect(parseInput("/usr/bin/python")).toEqual({ mode: "none" })
  })
  it("参数模式:带参命令 + 空格", () => {
    const p = parseInput("/model gpt")
    expect(p.mode).toBe("arg")
    if (p.mode === "arg") {
      expect(p.command.name).toBe("model")
      expect(p.arg).toBe("gpt")
    }
  })
  it("/model 加空格空参 → 参数模式空 arg", () => {
    const p = parseInput("/model ")
    expect(p.mode).toBe("arg")
    if (p.mode === "arg") expect(p.arg).toBe("")
  })
  it("无参命令 + 空格 → none(不进参数模式)", () => {
    expect(parseInput("/status ")).toEqual({ mode: "none" })
  })
  it("普通文本 → none", () => {
    expect(parseInput("hello")).toEqual({ mode: "none" })
  })
})

describe("matchCommands", () => {
  it("空前缀 → 全部", () => {
    expect(matchCommands("")).toHaveLength(COMMANDS.length)
  })
  it("前缀消歧 s*", () => {
    expect(matchCommands("se").map((c) => c.name)).toEqual(["settings"])
    expect(matchCommands("sk").map((c) => c.name)).toEqual(["skills"])
    expect(matchCommands("st").map((c) => c.name)).toEqual(["status"])
  })
})

describe("model.suggestions", () => {
  it("按 arg 前缀过滤(trim)", () => {
    const model = COMMANDS.find((c) => c.name === "model")!
    const ctx = { modelSuggestions: () => ["gpt-4o", "gpt-4o-mini", "claude"] } as never
    expect(model.suggestions!(ctx, "gpt")).toEqual(["gpt-4o", "gpt-4o-mini"])
    expect(model.suggestions!(ctx, " cl ")).toEqual(["claude"])
  })
})
