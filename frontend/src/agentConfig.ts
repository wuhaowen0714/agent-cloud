export const BUILTIN_TOOLS: { name: string; desc: string }[] = [
  { name: "bash", desc: "运行 shell 命令" },
  { name: "write_file", desc: "写文件" },
  { name: "read_file", desc: "读文件" },
  { name: "edit", desc: "改文件(精确替换)" },
  { name: "remember", desc: "主动记忆(把耐久事实写入长期记忆)" },
]
const ALL = BUILTIN_TOOLS.map((t) => t.name)

// agent.enabled_tools → 勾选集合(空 = 全部)
export function enabledToChecked(enabled: string[]): Set<string> {
  return new Set(enabled.length ? enabled : ALL)
}

// 勾选集合 → 保存值:全勾规范化为 [](= 全部),子集保存子集(按内置顺序)
export function checkedToEnabled(checked: Set<string>): string[] {
  const list = ALL.filter((n) => checked.has(n))
  return list.length === ALL.length ? [] : list
}
