class AgentConfig {
  final String id;
  final String name;
  const AgentConfig({required this.id, required this.name});

  factory AgentConfig.fromJson(Map<String, dynamic> j) =>
      AgentConfig(id: j['id'] as String, name: j['name'] as String);
}
