/// 聊天正文里的工作区路径识别(inline code → 可点链接;对标 web workspacePaths.ts)。
/// 只认「文件索引里真实存在」的路径:精确 → 文件;目录前缀 → 目录;裸文件名全工作区唯一
/// → 该文件;其余(多义/不存在/URL/含空白)不链接,绝不误伤普通代码片段。
typedef PathHit = ({String path, bool isDir});

final _scheme = RegExp(r'^[a-z]+://', caseSensitive: false);

PathHit? resolveWorkspacePath(String raw, List<String> index) {
  final text = raw.trim();
  if (text.isEmpty || text.length > 200) return null;
  if (RegExp(r'\s').hasMatch(text)) return null;
  if (_scheme.hasMatch(text) || text.startsWith('/')) return null;
  final p = text.replaceFirst(RegExp(r'/+$'), '');
  if (p.isEmpty) return null;
  if (index.contains(p)) return (path: p, isDir: false);
  final prefix = '$p/';
  if (index.any((f) => f.startsWith(prefix))) return (path: p, isDir: true);
  if (!p.contains('/')) {
    final matches =
        index.where((f) => f == p || f.endsWith('/$p')).toList();
    if (matches.length == 1) return (path: matches.first, isDir: false);
  }
  return null;
}
