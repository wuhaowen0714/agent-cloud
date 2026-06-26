// 上传附件的发送组装(对标 web Composer):图片走多模态 vision(images[]),其余文件把
// 工作区路径作为文本引用拼进正文,让 agent 用 read_file 读取。

final _imageExt = RegExp(r'\.(png|jpe?g|gif|webp|bmp)$', caseSensitive: false);

/// 路径是否图片(决定走 vision 还是文本引用)。
bool isImagePath(String path) => _imageExt.hasMatch(path);

/// 把正文 + 上传后的工作区路径组装成 (发给 vision 的图片路径, 最终正文)。
/// 非图片文件追加一段「已上传…可用 read_file 读取」+ 路径清单到正文。
({List<String> images, String content}) composeUpload(
    String text, List<String> uploadedPaths) {
  final images = uploadedPaths.where(isImagePath).toList();
  var content = text;
  // 所有路径(含图片)都进文本引用:让 agent 能对图片 read_file/edit_image(对标 web);
  // 图片同时进 images[] 走多模态 vision。
  if (uploadedPaths.isNotEmpty) {
    final refs =
        '[已上传文件到工作区,可用 read_file 读取;图片可用 edit_image 编辑]\n${uploadedPaths.join('\n')}';
    content = text.isEmpty ? refs : '$text\n\n$refs';
  }
  return (images: images, content: content);
}
