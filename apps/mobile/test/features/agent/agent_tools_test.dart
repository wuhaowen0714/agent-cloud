import 'package:flutter_test/flutter_test.dart';
import 'package:agent_cloud_mobile/features/agent/agent_tools.dart';

void main() {
  test('客户端动作工具(含 start_navigation)都在工具清单里', () {
    final names = kBuiltinTools.map((t) => t.name).toSet();
    expect(
      names.containsAll({'set_alarm', 'add_calendar_event', 'start_navigation'}),
      isTrue,
    );
  });

  test('notify 不在 app 工具清单(app 无通知接收通道;worker 也按 client=mobile 门控)', () {
    expect(kBuiltinTools.map((t) => t.name).contains('notify'), isFalse);
  });

  test('enabled_tools 空 → 全部勾选(含 start_navigation)', () {
    expect(enabledToChecked([]).contains('start_navigation'), isTrue);
  });

  test('关掉某工具后 enabled_tools 仍保留 start_navigation(否则 worker 门控会丢导航)', () {
    // 防回归:客户端动作工具必须在清单里,否则关任意工具时 checkedToEnabled
    // 取不到它 → enabled_tools 非空且不含它 → worker 关掉导航。
    final all = kBuiltinTools.map((t) => t.name).toSet();
    final next = {...all}..remove('bash'); // 关掉 bash → 非全选子集
    final enabled = checkedToEnabled(next);
    expect(enabled, isNotEmpty); // 非全选 → 非空(显式列出子集)
    expect(enabled.contains('start_navigation'), isTrue);
  });

  test('全勾规范化为空(=全部启用)', () {
    final all = kBuiltinTools.map((t) => t.name).toSet();
    expect(checkedToEnabled(all), isEmpty);
  });
}
