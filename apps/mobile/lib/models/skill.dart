/// 已安装技能。
class Skill {
  final String id;
  final String name;
  final String description;
  final String source; // builtin / workspace / upload 等
  final String version;

  const Skill({
    required this.id,
    required this.name,
    required this.description,
    required this.source,
    required this.version,
  });

  factory Skill.fromJson(Map<String, dynamic> j) => Skill(
        id: j['id'] as String,
        name: j['name'] as String,
        description: j['description'] as String? ?? '',
        source: j['source'] as String? ?? '',
        version: j['version'] as String? ?? '',
      );
}
