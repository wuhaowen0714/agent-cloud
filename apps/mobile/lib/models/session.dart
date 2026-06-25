class Session {
  final String id;
  final String agentConfigId;
  final String model;
  final String? title;
  final String status;

  const Session({
    required this.id,
    required this.agentConfigId,
    required this.model,
    required this.title,
    required this.status,
  });

  factory Session.fromJson(Map<String, dynamic> j) => Session(
        id: j['id'] as String,
        agentConfigId: j['agent_config_id'] as String,
        model: j['model'] as String,
        title: j['title'] as String?,
        status: j['status'] as String,
      );

  /// 列表展示标题:无 title 用"新会话"占位。
  String get displayTitle => (title != null && title!.isNotEmpty) ? title! : '新会话';
}
