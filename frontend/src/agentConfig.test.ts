import { describe, expect, it } from "vitest"
import { BUILTIN_TOOLS, checkedToEnabled, enabledToChecked } from "./agentConfig"

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
