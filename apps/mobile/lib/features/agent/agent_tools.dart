/// 内置工具清单 + enabled_tools 转换(对标 web agentConfig.ts)。
class ToolInfo {
  final String name;
  final String desc;
  const ToolInfo(this.name, this.desc);
}

const kBuiltinTools = <ToolInfo>[
  ToolInfo('bash', '运行 shell 命令'),
  ToolInfo('write_file', '写文件'),
  ToolInfo('read_file', '读文件'),
  ToolInfo('edit', '改文件(精确替换)'),
  ToolInfo('remember', '主动记忆(把耐久事实写入长期记忆)'),
  ToolInfo('schedule_task', '定时任务(自助排期周期性运行)'),
  ToolInfo('web_search', '联网搜索(获取实时网页信息)'),
  ToolInfo('generate_image', '文生图(按文字描述生成图片)'),
  ToolInfo('edit_image', '图片编辑(按文字描述修改图片)'),
  ToolInfo('set_alarm', '设置手机闹钟(仅 App 生效)'),
  ToolInfo('add_calendar_event', '添加手机日历事件(仅 App 生效)'),
  ToolInfo('start_navigation', '唤起地图导航(高德/百度,仅 App 生效)'),
];

final _allToolNames = kBuiltinTools.map((t) => t.name).toList();

/// enabled_tools → 勾选集(空 = 全部启用)。
Set<String> enabledToChecked(List<String> enabled) =>
    enabled.isNotEmpty ? enabled.toSet() : _allToolNames.toSet();

/// 勾选集 → 保存值(全勾规范化为 [] = 全部,子集按内置顺序)。
List<String> checkedToEnabled(Set<String> checked) {
  final list = _allToolNames.where(checked.contains).toList();
  return list.length == _allToolNames.length ? [] : list;
}
