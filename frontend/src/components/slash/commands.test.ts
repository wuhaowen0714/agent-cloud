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
  it("/skills 带参:进参数模式(选技能)", () => {
    const p = parseInput("/skills 文档")
    expect(p.mode).toBe("arg")
    if (p.mode === "arg") {
      expect(p.command.name).toBe("skills")
      expect(p.arg).toBe("文档")
    }
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

describe("skills 命令", () => {
  const skills = COMMANDS.find((c) => c.name === "skills")!

  it("是带参命令(needsArg)", () => {
    expect(skills.needsArg).toBe(true)
  })

  it("suggestions:按 arg 子串过滤(不分大小写)", () => {
    const ctx = { skillSuggestions: () => ["PDF Reader", "docx", "图片生成"] } as never
    expect(skills.suggestions!(ctx, "pdf")).toEqual(["PDF Reader"])
    expect(skills.suggestions!(ctx, "图片")).toEqual(["图片生成"])
    expect(skills.suggestions!(ctx, "")).toEqual(["PDF Reader", "docx", "图片生成"])
  })

  it("runWithArg:启用成功 → 把技能选进 Composer(显示成 chip)", async () => {
    const picked: string[] = []
    const ctx = {
      enableSkill: async () => "enabled" as const,
      selectSkill: (n: string) => picked.push(n),
      notify: () => {},
    } as never
    await skills.runWithArg!(ctx, "docx")
    expect(picked).toEqual(["docx"])
  })

  it("runWithArg:已启用也选进 Composer(幂等)", async () => {
    const picked: string[] = []
    const ctx = {
      enableSkill: async () => "already" as const,
      selectSkill: (n: string) => picked.push(n),
      notify: () => {},
    } as never
    await skills.runWithArg!(ctx, "pptx")
    expect(picked).toEqual(["pptx"])
  })

  it("runWithArg:未找到 → 提示", async () => {
    const calls: string[] = []
    const ctx = {
      enableSkill: async () => "notfound" as const,
      notify: (m: string) => calls.push(m),
    } as never
    await skills.runWithArg!(ctx, "xxx")
    expect(calls[0]).toContain("没有找到")
  })

  it("runWithArg:空 arg 不调用 enableSkill", async () => {
    let called = false
    const ctx = {
      enableSkill: async () => {
        called = true
        return "enabled" as const
      },
      notify: () => {},
    } as never
    await skills.runWithArg!(ctx, "  ")
    expect(called).toBe(false)
  })
})
