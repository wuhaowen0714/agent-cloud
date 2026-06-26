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

  test('composeUpload:空正文 + 纯文件 → 正文只有引用段(英文 marker,对标 web)', () {
    final r = composeUpload('', ['uploads/x.zip']);
    expect(r.content, startsWith('[Uploaded file(s) in the workspace'));
    expect(r.images, isEmpty);
  });

  test('composeUpload:无附件 → 原样', () {
    final r = composeUpload('你好', []);
    expect(r.images, isEmpty);
    expect(r.content, '你好');
  });

  // composeUpload 与 parseUserMessage 互逆:发送拼的 marker 能被渲染端解析回正文 + 附件。
  test('composeUpload → parseUserMessage 往返:正文与附件还原', () {
    final c = composeUpload('描述一下这个图片', ['uploads/shot.jpg']);
    final p = parseUserMessage(c.content);
    expect(p.body, '描述一下这个图片');
    expect(p.attachments, ['uploads/shot.jpg']);
  });

  group('parseUserMessage', () {
    const marker =
        '[Uploaded file(s) in the workspace — read with read_file, or edit images with edit_image]';

    test('摘出附件路径,正文只留用户文本', () {
      final r = parseUserMessage('总结这个文档\n\n$marker\nuploads/report.pdf');
      expect(r.body, '总结这个文档');
      expect(r.attachments, ['uploads/report.pdf']);
    });

    test('多个附件(图片 + 文件混合)', () {
      final r =
          parseUserMessage('看这些\n\n$marker\nuploads/a.png\nuploads/b.pdf');
      expect(r.attachments, ['uploads/a.png', 'uploads/b.pdf']);
    });

    test('仅附件无正文 → body 为空', () {
      final r = parseUserMessage('$marker\nuploads/data.xlsx');
      expect(r.body, '');
      expect(r.attachments, ['uploads/data.xlsx']);
    });

    test('文件名含空格', () {
      final r = parseUserMessage('x\n\n$marker\nuploads/my report final.pdf');
      expect(r.attachments, ['uploads/my report final.pdf']);
    });

    test('无 marker → 原样返回,无附件', () {
      final r = parseUserMessage('你好');
      expect(r.body, '你好');
      expect(r.attachments, isEmpty);
    });

    // 对抗审查 H1:用户正文恰好含 marker 样式文本,后接真实正文(非路径)→ 不能吞正文。
    test('正文含 marker 样式但后接正文(非路径)→ 不解析,原样保留', () {
      final t = '$marker\n这不是路径而是正文,在问这个功能本身';
      final r = parseUserMessage(t);
      expect(r.body, t);
      expect(r.attachments, isEmpty);
    });

    // 兼容 app 早期中文 marker(线上历史消息):同样要能隐藏。
    test('兼容早期中文 marker', () {
      final r = parseUserMessage(
          '这是什么\n\n[已上传文件到工作区,可用 read_file 读取;图片可用 edit_image 编辑]\nuploads/cat.png');
      expect(r.body, '这是什么');
      expect(r.attachments, ['uploads/cat.png']);
    });

    // 兼容 web 早期 Attached image marker + web 的 upload/(单数)路径。
    test('兼容 web Attached image marker 与 upload/ 路径', () {
      final r = parseUserMessage(
          '这是什么\n\n[Attached image(s) in the workspace]\nupload/cat.png');
      expect(r.body, '这是什么');
      expect(r.attachments, ['upload/cat.png']);
    });

    // media/ 路径(generate_image 落盘)也算工作区附件。
    test('media/ 路径也认', () {
      final r = parseUserMessage('$marker\nmedia/picture/x.png');
      expect(r.attachments, ['media/picture/x.png']);
    });

    test('技能 marker:摘出技能名,正文留用户文本', () {
      final r = parseUserMessage('帮我整理\n\n[请使用技能:文档整理]');
      expect(r.body, '帮我整理');
      expect(r.skills, ['文档整理']);
    });

    // M1(对标 web):fork 回填可能产生多段 marker;只收工作区路径行,过滤残留 marker 行。
    test('多段 marker:只收路径行,过滤残留 marker 行', () {
      final r = parseUserMessage(
          '问题\n\n$marker\nuploads/a.png\n\n$marker\nuploads/b.png');
      expect(r.attachments, ['uploads/a.png', 'uploads/b.png']);
    });

    // M2:CRLF 也要正常解析(否则 marker + 裸路径原样暴露)。
    test('CRLF 换行也能解析', () {
      final r = parseUserMessage('总结\r\n\r\n$marker\r\nuploads/x.pdf');
      expect(r.body, '总结');
      expect(r.attachments, ['uploads/x.pdf']);
    });

    // 对抗 H1 延伸:marker 后即便有一行真路径,只要混入一行非路径就整体不解析、保留正文。
    test('marker 后混入非路径行 → 整体不解析,保留正文', () {
      final t = 'hi\n\n$marker\nuploads/ok.png\nrandom note here';
      final r = parseUserMessage(t);
      expect(r.body, t);
      expect(r.attachments, isEmpty);
    });

    // 对抗 High:正文句中内联打 [请使用技能:x] 不能被吞(技能 marker 整行锚定)。
    test('正文句中内联 [请使用技能:x] 不被吞', () {
      const t = '这个功能怎么用?我打 [请使用技能:foo] 会怎样';
      final r = parseUserMessage(t);
      expect(r.body, t);
      expect(r.skills, isEmpty);
    });

    // 技能名含逗号/顿号不切碎(每技能独占一行,不靠分隔符 split)。
    test('技能名含逗号也不切碎', () {
      final r = parseUserMessage('x\n\n[请使用技能:数据,分析]');
      expect(r.skills, ['数据,分析']);
    });
  });
}
