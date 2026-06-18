import type { Skill } from "./types"

// 内置技能(后端 registry:docx/pptx/xlsx/skill-creator)的 description 是写给【模型】的
// 英文触发条件——又长又是英文,直接展示给用户看不懂(用户反馈)。这里按技能名维护一份
// 中文短描述,仅用于 UI 展示。后端/DB 里的 description 一字不动(它仍被喂给模型做"何时调用
// 该技能"的匹配,见 worker context),所以改这里不影响技能匹配、且对所有用户即时生效。
// 未收录的技能(用户自造/上传)回退其自带 description(多半本就是中文)。
const SKILL_DESCRIPTION_ZH: Record<string, string> = {
  docx: "创建、读取、编辑 Word 文档(.docx)",
  pptx: "创建、读取、编辑 PPT 演示文稿(.pptx)",
  xlsx: "创建、读取、编辑 Excel 表格(.xlsx/.csv)",
  "skill-creator": "创建新技能:生成 SKILL.md 脚手架",
}

// 技能在 UI 上的展示描述:内置技能用中文短描述,其余回退自带 description。
export function skillDescription(skill: Pick<Skill, "name" | "description">): string {
  return SKILL_DESCRIPTION_ZH[skill.name] ?? skill.description
}
