import 'package:flutter_test/flutter_test.dart';
import 'package:agent_cloud_mobile/features/chat/upload_compose.dart';

void main() {
  test('isImagePath 识别图片扩展名', () {
    expect(isImagePath('uploads/a.png'), true);
    expect(isImagePath('uploads/b.JPG'), true);
    expect(isImagePath('uploads/c.jpeg'), true);
    expect(isImagePath('uploads/d.webp'), true);
    expect(isImagePath('uploads/e.pdf'), false);
    expect(isImagePath('uploads/f.docx'), false);
    expect(isImagePath('uploads/g.txt'), false);
  });

  test('composeUpload:纯图片 → images,图片路径也进文本引用(对标 web)', () {
    final r = composeUpload('看看这张图', ['uploads/a.png', 'uploads/b.jpg']);
    expect(r.images, ['uploads/a.png', 'uploads/b.jpg']);
    expect(r.content, startsWith('看看这张图'));
    expect(r.content, contains('uploads/a.png'));
    expect(r.content, contains('uploads/b.jpg'));
  });

  test('composeUpload:纯文件 → 文本引用,images 空', () {
    final r = composeUpload('帮我看', ['uploads/doc.pdf', 'uploads/data.csv']);
    expect(r.images, isEmpty);
    expect(r.content, contains('read_file'));
    expect(r.content, contains('uploads/doc.pdf'));
    expect(r.content, contains('uploads/data.csv'));
    expect(r.content, startsWith('帮我看'));
  });

  test('composeUpload:混合 → 图片走 images,所有路径(含图)进文本引用', () {
    final r = composeUpload('', ['uploads/a.png', 'uploads/doc.pdf']);
    expect(r.images, ['uploads/a.png']);
    expect(r.content, contains('uploads/doc.pdf'));
    expect(r.content, contains('uploads/a.png')); // 图片也进文本(可 edit_image)
  });

  test('composeUpload:空正文 + 纯文件 → 正文只有引用段', () {
    final r = composeUpload('', ['uploads/x.zip']);
    expect(r.content, startsWith('[已上传文件'));
    expect(r.images, isEmpty);
  });

  test('composeUpload:无附件 → 原样', () {
    final r = composeUpload('你好', []);
    expect(r.images, isEmpty);
    expect(r.content, '你好');
  });
}
