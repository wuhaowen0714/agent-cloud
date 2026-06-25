import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:agent_cloud_mobile/features/auth/login_page.dart';

void main() {
  setUp(() => FlutterSecureStorage.setMockInitialValues({}));

  testWidgets('登录页渲染 + 切到注册', (tester) async {
    await tester
        .pumpWidget(const ProviderScope(child: MaterialApp(home: LoginPage())));
    expect(find.text('登录'), findsWidgets);
    await tester.tap(find.text('没有账号?去注册'));
    await tester.pump();
    expect(find.text('注册'), findsWidgets);
  });
}
