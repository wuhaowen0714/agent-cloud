class ContextDocument {
  final String id;
  final String scope;
  final String type;
  final String content;

  const ContextDocument({
    required this.id,
    required this.scope,
    required this.type,
    required this.content,
  });

  factory ContextDocument.fromJson(Map<String, dynamic> j) => ContextDocument(
        id: j['id'] as String,
        scope: j['scope'] as String,
        type: j['type'] as String,
        content: j['content'] as String? ?? '',
      );
}
