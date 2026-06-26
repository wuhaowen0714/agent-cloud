import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:agent_cloud_mobile/features/files/files_browser_page.dart';
import 'package:agent_cloud_mobile/features/files/files_repository.dart';
import 'package:agent_cloud_mobile/models/file_entry.dart';

void main() {
  const items = [
    FileEntry(name: '.hidden_dir', path: '.hidden_dir', isDir: true, size: 0),
    FileEntry(name: '.env', path: '.env', isDir: false, size: 20),
    FileEntry(name: 'visible.txt', path: 'visible.txt', isDir: false, size: 100),
    FileEntry(name: 'code.py', path: 'code.py', isDir: false, size: 200),
  ];

  Widget app() => ProviderScope(
        overrides: [
          // 根目录列表注入固定数据,避开真实 dio。
          filesListProvider('').overrideWith((ref) => Future.value(items)),
        ],
        child: const MaterialApp(home: FilesPage()),
      );

  testWidgets('默认隐藏「.」开头的文件/夹,可见项正常显示', (tester) async {
    await tester.pumpWidget(app());
    await tester.pumpAndSettle();
    // 普通文件显示
    expect(find.text('visible.txt'), findsOneWidget);
    expect(find.text('code.py'), findsOneWidget);
    // . 开头默认隐藏
    expect(find.text('.hidden_dir'), findsNothing);
    expect(find.text('.env'), findsNothing);
  });

  testWidgets('点眼睛图标后显示隐藏文件,再点又隐藏', (tester) async {
    await tester.pumpWidget(app());
    await tester.pumpAndSettle();
    expect(find.text('.env'), findsNothing);

    await tester.tap(find.byTooltip('显示隐藏文件'));
    await tester.pumpAndSettle();
    expect(find.text('.hidden_dir'), findsOneWidget);
    expect(find.text('.env'), findsOneWidget);

    await tester.tap(find.byTooltip('隐藏「.」开头文件'));
    await tester.pumpAndSettle();
    expect(find.text('.env'), findsNothing);
  });

  testWidgets('每个文件行带下载按钮,目录不带', (tester) async {
    await tester.pumpWidget(app());
    await tester.pumpAndSettle();
    // 默认显示 2 个普通文件 → 2 个下载按钮(目录走 chevron 不显示)
    expect(find.byTooltip('下载'), findsNWidgets(2));
  });
}
