class Session {
  final String id;
  final String agentConfigId;
  final String model;
  final String? title;
  final String status;
  final DateTime? lastActiveAt;
  final bool unread; // 定时任务产物:有新回复未读
  final String? lastMessage; // 列表预览:最后一条主消息截断文本(可能含 marker,渲染时剥)

  const Session({
    required this.id,
    required this.agentConfigId,
    required this.model,
    required this.title,
    required this.status,
    this.lastActiveAt,
    this.unread = false,
    this.lastMessage,
  });

  factory Session.fromJson(Map<String, dynamic> j) => Session(
        id: j['id'] as String,
        agentConfigId: j['agent_config_id'] as String,
        model: j['model'] as String,
        title: j['title'] as String?,
        status: j['status'] as String,
        lastActiveAt: j['last_active_at'] != null
            ? DateTime.tryParse(j['last_active_at'] as String)
            : null,
        unread: j['unread'] as bool? ?? false,
        lastMessage: j['last_message'] as String?,
      );

  Session copyWith({
    String? model,
    String? title,
    String? status,
    DateTime? lastActiveAt,
    bool? unread,
    String? lastMessage,
  }) =>
      Session(
        id: id,
        agentConfigId: agentConfigId,
        model: model ?? this.model,
        title: title ?? this.title,
        status: status ?? this.status,
        unread: unread ?? this.unread,
        lastMessage: lastMessage ?? this.lastMessage,
        lastActiveAt: lastActiveAt ?? this.lastActiveAt,
      );

  /// 列表展示标题:无 title 用"新会话"占位。
  String get displayTitle =>
      (title != null && title!.isNotEmpty) ? title! : '新会话';

  /// 最后活跃的相对时间(刚刚 / x 分钟前 / x 小时前 / x 天前 / 日期)。
  String get relativeTime {
    final t = lastActiveAt;
    if (t == null) return '';
    final d = DateTime.now().difference(t);
    if (d.inMinutes < 1) return '刚刚';
    if (d.inMinutes < 60) return '${d.inMinutes} 分钟前';
    if (d.inHours < 24) return '${d.inHours} 小时前';
    if (d.inDays < 30) return '${d.inDays} 天前';
    return '${t.year}-${t.month.toString().padLeft(2, '0')}-'
        '${t.day.toString().padLeft(2, '0')}';
  }
}
