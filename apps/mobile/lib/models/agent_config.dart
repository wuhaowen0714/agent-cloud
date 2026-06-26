class AgentConfig {
  final String id;
  final String name;
  final List<String> enabledTools; // 空 = 全部启用

  const AgentConfig({
    required this.id,
    required this.name,
    this.enabledTools = const [],
  });

  factory AgentConfig.fromJson(Map<String, dynamic> j) => AgentConfig(
        id: j['id'] as String,
        name: j['name'] as String,
        enabledTools:
            ((j['enabled_tools'] as List?) ?? const []).cast<String>(),
      );
}
