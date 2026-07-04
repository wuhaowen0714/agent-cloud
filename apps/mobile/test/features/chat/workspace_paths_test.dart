import 'package:flutter_test/flutter_test.dart';
import 'package:agent_cloud_mobile/features/chat/workspace_paths.dart';

void main() {
  const index = [
    'documents/python-study-plan/README.md',
    'documents/python-study-plan/week1-2-basics/README.md',
    'documents/report/final.docx',
    'notes.txt',
  ];

  test('精确路径 → 文件;目录前缀 → 目录(含尾斜杠)', () {
    expect(resolveWorkspacePath('documents/report/final.docx', index),
        (path: 'documents/report/final.docx', isDir: false));
    expect(resolveWorkspacePath('documents/python-study-plan/', index),
        (path: 'documents/python-study-plan', isDir: true));
    expect(resolveWorkspacePath('documents', index),
        (path: 'documents', isDir: true));
  });

  test('裸文件名唯一 → 链接;多义/不存在/URL/绝对路径/含空白 → null', () {
    expect(resolveWorkspacePath('final.docx', index),
        (path: 'documents/report/final.docx', isDir: false));
    expect(resolveWorkspacePath('notes.txt', index),
        (path: 'notes.txt', isDir: false));
    expect(resolveWorkspacePath('README.md', index), isNull); // 两处,宁可不跳
    expect(resolveWorkspacePath('ghost.md', index), isNull);
    expect(resolveWorkspacePath('https://x.com/a.md', index), isNull);
    expect(resolveWorkspacePath('/etc/passwd', index), isNull);
    expect(resolveWorkspacePath('pip install x', index), isNull);
  });
}
