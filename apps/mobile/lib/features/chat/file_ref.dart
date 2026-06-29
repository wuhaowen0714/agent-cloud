// @ 文件引用的纯函数(移植 web fileRef.ts):由「文本 + 光标」派生当前 @ 词,再对文件索引
// 做子串过滤。无状态/UI 依赖,便于单测。逐行对齐 web 逻辑。

class AtToken {
  final int start; // "@" 在 text 中的下标(替换区间 [start, caret) 的左端)
  final String query; // "@" 之后到光标的内容(过滤词;兼容中文)
  const AtToken(this.start, this.query);

  @override
  bool operator ==(Object other) =>
      other is AtToken && other.start == start && other.query == query;
  @override
  int get hashCode => Object.hash(start, query);
}

final _ws = RegExp(r'\s');

/// 光标所在词以 "@" 开头才算引用词。向左扫到空白/行首即词首——天然保证 "@" 前是空白或
/// 文本开头(邮箱 a@b 的词首是 "a",不触发)。词内再次出现 "@"(如 @a@b)视为放弃引用。
/// 光标恰在 "@" 前(caret == start)属于词外,不触发。
AtToken? atTokenAt(String text, int caret) {
  if (caret < 0 || caret > text.length) return null;
  var start = caret;
  while (start > 0 && !_ws.hasMatch(text[start - 1])) {
    start--;
  }
  if (caret <= start || start >= text.length || text[start] != '@') return null;
  final query = text.substring(start + 1, caret);
  return query.contains('@') ? null : AtToken(start, query);
}

/// 不区分大小写的子串匹配(路径任意位置,目录名也能命中),保序截断到 max。
List<String> filterPaths(List<String> paths, String query, {int max = 20}) {
  final q = query.toLowerCase();
  final out = <String>[];
  for (final p in paths) {
    if (p.toLowerCase().contains(q)) {
      out.add(p);
      if (out.length >= max) break;
    }
  }
  return out;
}
