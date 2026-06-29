// 上传附件的发送组装 + 用户气泡解析(对标 web Composer + chatText.parseUserMessage)。
// 图片走多模态 vision(images[]);所有文件(含图)把工作区路径作为文本引用拼进正文,让 agent
// 用 read_file 读取 / edit_image 编辑。marker 文案与 web 逐字一致,故两端发的消息能被同一套
// parseUserMessage 摘成 chip(app 早期中文 marker 也兼容解析)。

final _imageExt = RegExp(r'\.(png|jpe?g|gif|webp|bmp)$', caseSensitive: false);

/// 路径是否图片(决定走 vision 还是文本引用)。
bool isImagePath(String path) => _imageExt.hasMatch(path);

// 发送时拼进正文的附件 marker —— 与 web Composer.send 逐字一致(含 em dash —)。
const _uploadMarker =
    '[Uploaded file(s) in the workspace — read with read_file, or edit images with edit_image]';

/// 把正文 + 选中技能 + 上传附件组装成 (发给 vision 的图片路径, 最终正文)。三段【空行分隔】,
/// 与 web Composer.send 逐字一致:① 用户正文(含 @路径原样保留,后端靠 read_file 理解)② 技能段
/// (每技能独占一行 [请使用技能:X],半角冒号——与 parseUserMessage 的 _skillLine 同字符)③ 附件段
/// (marker + 路径清单)。图片同时进 images[] 走多模态 vision;渲染气泡时 parseUserMessage 摘 chip。
({List<String> images, String content}) composeMessage(
    String text, List<String> skills, List<String> uploadedPaths) {
  final parts = <String>[];
  if (text.isNotEmpty) parts.add(text);
  if (skills.isNotEmpty) {
    parts.add(skills.map((s) => '[请使用技能:$s]').join('\n'));
  }
  if (uploadedPaths.isNotEmpty) {
    parts.add('$_uploadMarker\n${uploadedPaths.join('\n')}');
  }
  final images = uploadedPaths.where(isImagePath).toList();
  return (images: images, content: parts.join('\n\n'));
}

/// 仅附件(无技能)的便捷封装,保持既有调用点不变。
({List<String> images, String content}) composeUpload(
        String text, List<String> uploadedPaths) =>
    composeMessage(text, const [], uploadedPaths);

// ── 渲染用户气泡时把发送拼进去的「marker + 工作区路径」段摘出来,正文只留用户真正打的字 ──
// (对标 web chatText.parseUserMessage)。图片已由消息 images 字段(缩略图)单独展示,非图片附件
// 渲染成文件 chip —— 而不是把内部提示 + 裸路径直接示人。
//
// ⚠️ marker 是【不可信用户文本】:用户正文可能恰好出现这串(贴报错、问这个功能本身),不能无脑
// 当分隔符。只有 marker 之后【每一行都是工作区路径】(uploads?//media/ 前缀)时才剥离;混入
// 其它文本则整体不解析、原样保留正文(对抗审查 H1,与 web 同源)。兼容三种 marker:web 英文
// Uploaded/Attached、app 早期中文「已上传文件到工作区」。
final _markerRe = RegExp(
    r'\[(?:Uploaded file\(s\) in the workspace|Attached image\(s\) in the workspace|已上传文件到工作区)[^\]\n]*\]\n');
final _markerLine = RegExp(
    r'^\[(?:Uploaded file\(s\) in the workspace|Attached image\(s\) in the workspace|已上传文件到工作区)[^\]]*\]$');
final _workspacePath = RegExp(r'^(?:uploads?|media)/');
// /skills 技能 marker(web 发的消息可能带;app 不发但要能在两端正确隐藏):整行锚定,每技能一行。
final _skillLine = RegExp(r'^\[请使用技能:\s*([^\]]+)\]$');

/// 解析用户消息 content → (正文 body, 附件路径 attachments, 技能 skills)。无 marker 原样返回。
({String body, List<String> attachments, List<String> skills}) parseUserMessage(
    String text) {
  final normalized = text.replaceAll('\r\n', '\n'); // CRLF 归一,否则 marker/路径不匹配会暴露
  // 1. 逐行摘出独占整行的技能 marker;其余行保留(防误吞正文)。
  final skills = <String>[];
  final kept = <String>[];
  for (final line in normalized.split('\n')) {
    final sm = _skillLine.firstMatch(line.trim());
    if (sm != null) {
      skills.add(sm.group(1)!.trim());
    } else {
      kept.add(line);
    }
  }
  final hadSkill = skills.isNotEmpty;
  final work = hadSkill
      ? kept.join('\n').replaceAll(RegExp(r'\n{3,}'), '\n\n').trim()
      : normalized;
  final fallbackBody = hadSkill ? work : text; // 无 skill 时保「无 marker 原样」语义
  // 2. 附件 marker:其后每行必须是工作区路径(或多段附件残留的 marker 行)才剥离。
  final m = _markerRe.firstMatch(work);
  if (m == null) {
    return (body: fallbackBody, attachments: const <String>[], skills: skills);
  }
  final rest = work
      .substring(m.end)
      .split('\n')
      .map((l) => l.trim())
      .where((l) => l.isNotEmpty)
      .toList();
  if (rest.isEmpty ||
      !rest.every(
          (l) => _workspacePath.hasMatch(l) || _markerLine.hasMatch(l))) {
    return (body: fallbackBody, attachments: const <String>[], skills: skills);
  }
  final attachments = rest.where((l) => _workspacePath.hasMatch(l)).toList();
  if (attachments.isEmpty) {
    return (body: fallbackBody, attachments: const <String>[], skills: skills);
  }
  return (
    body: work.substring(0, m.start).trim(),
    attachments: attachments,
    skills: skills,
  );
}
