// set_alarm / add_calendar_event 不在此列:它们是 mobile App 固有能力(web 没有系统闹钟/
// 日历的执行通道),web 工具开关不显示;后端按客户端平台过滤(web 回合不把它们暴露给 LLM)。
// mobile App 的工具列表(apps/mobile agent_tools.dart)里仍有这俩。
export const BUILTIN_TOOLS: { name: string; desc: string }[] = [
  { name: "bash", desc: "运行 shell 命令" },
  { name: "write_file", desc: "写文件" },
  { name: "read_file", desc: "读文件" },
  { name: "edit", desc: "改文件(精确替换)" },
  { name: "remember", desc: "主动记忆(把耐久事实写入长期记忆)" },
  { name: "schedule_task", desc: "定时任务(让 agent 自助排期周期性运行)" },
  { name: "notify", desc: "提醒用户(系统通知 + 网页弹窗)" },
  { name: "web_search", desc: "联网搜索(获取实时网页信息)" },
  { name: "generate_image", desc: "文生图(按文字描述生成图片)" },
  { name: "edit_image", desc: "图片编辑(按文字描述修改图片)" },
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

// 一键新建 agent 的默认名:现有「Agent k」最大 k+1(无则 1);其它名字(main 等)不参与。
export function nextAgentName(existing: string[]): string {
  let max = 0
  for (const n of existing) {
    const m = /^Agent (\d+)$/.exec(n.trim())
    if (m) max = Math.max(max, Number(m[1]))
  }
  return `Agent ${max + 1}`
}
