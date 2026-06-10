import { describe, expect, it } from "vitest"
import { BUILTIN_TOOLS, checkedToEnabled, enabledToChecked, nextAgentName } from "./agentConfig"

describe("nextAgentName", () => {
  it("空表 → Agent 1", () => {
    expect(nextAgentName([])).toBe("Agent 1")
  })
  it("取 Agent k 最大值 +1,忽略非模式名", () => {
    expect(nextAgentName(["main", "Agent 2", "Agent 9", "agentx"])).toBe("Agent 10")
  })
})

describe("tool helpers", () => {
  it("empty enabled_tools means all checked", () => {
    expect(enabledToChecked([])).toEqual(new Set(BUILTIN_TOOLS.map((t) => t.name)))
  })
  it("a subset stays that subset", () => {
    expect(enabledToChecked(["bash"])).toEqual(new Set(["bash"]))
  })
  it("all checked normalizes to [] (= all)", () => {
    expect(checkedToEnabled(new Set(BUILTIN_TOOLS.map((t) => t.name)))).toEqual([])
  })
  it("a subset saves as that subset, in canonical order", () => {
    expect(checkedToEnabled(new Set(["read_file", "bash"]))).toEqual(["bash", "read_file"])
  })
})
