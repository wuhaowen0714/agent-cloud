import { describe, expect, it } from "vitest"
import { skillDescription } from "./skillText"

describe("skillDescription", () => {
  it("内置技能返回中文短描述(忽略后端英文 description)", () => {
    expect(
      skillDescription({ name: "docx", description: "Use this skill whenever the user wants…" }),
    ).toBe("创建、读取、编辑 Word 文档(.docx)")
    expect(skillDescription({ name: "pptx", description: "Use this skill any time a .pptx…" })).toBe(
      "创建、读取、编辑 PPT 演示文稿(.pptx)",
    )
    expect(skillDescription({ name: "xlsx", description: "Use this skill any time a spreadsheet…" })).toBe(
      "创建、读取、编辑 Excel 表格(.xlsx/.csv)",
    )
    expect(
      skillDescription({ name: "skill-creator", description: "Author a new agent-cloud skill…" }),
    ).toBe("创建新技能:生成 SKILL.md 脚手架")
  })

  it("未收录技能(自造/上传)回退其自带 description", () => {
    expect(skillDescription({ name: "zippy", description: "我的自定义技能" })).toBe("我的自定义技能")
  })
})
