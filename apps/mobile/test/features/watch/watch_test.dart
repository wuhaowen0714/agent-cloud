import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:http_mock_adapter/http_mock_adapter.dart';
import 'package:agent_cloud_mobile/features/auth/auth_controller.dart';
import 'package:agent_cloud_mobile/features/watch/watch_center_page.dart';
import 'package:agent_cloud_mobile/features/watch/watch_repository.dart';
import 'package:agent_cloud_mobile/models/scheduled_task.dart';

Map<String, dynamic> _task({
  String id = 't1',
  String name = '晨报',
  bool enabled = true,
  String? lastStatus = 'ok',
}) =>
    {
      'id': id,
      'agent_config_id': 'a1',
      'name': name,
      'prompt': '整理 AI 新闻',
      'schedule_kind': 'cron',
      'schedule_expr': '0 8 * * *',
      'enabled': enabled,
      'next_run_at':
          DateTime.now().add(const Duration(hours: 3)).toIso8601String(),
      'last_run_at': DateTime.now().toIso8601String(),
      'last_status': lastStatus,
    };

void main() {
  test('ScheduledTask.fromJson + scheduleLabel', () {
    final t = ScheduledTask.fromJson(_task());
    expect(t.name, '晨报');
    expect(t.scheduleLabel, contains('Cron'));
    expect(t.enabled, isTrue);
    // 后端把 interval 归一化成纯秒:展示要转回人话
    ScheduledTask interval(String expr) => ScheduledTask.fromJson(_task()
      ..['schedule_kind'] = 'interval'
      ..['schedule_expr'] = expr);
    expect(interval('1800').scheduleLabel, '每 30 分钟');
    expect(interval('3600').scheduleLabel, '每 1 小时');
    expect(interval('86400').scheduleLabel, '每 1 天');
    expect(interval('90').scheduleLabel, '每 90 秒');
  });

  test('repository:list/create/setEnabled/runNow 请求形状', () async {
    final dio = Dio(BaseOptions(baseUrl: 'http://x/api'));
    final a = DioAdapter(dio: dio);
    a.onGet('/scheduled-tasks', (s) => s.reply(200, [_task()]));
    a.onPost('/scheduled-tasks', (s) => s.reply(201, _task(id: 't2')),
        data: {
          'name': 'n',
          'prompt': 'p',
          'agent_config_id': 'a1',
          'schedule_kind': 'interval',
          'schedule_expr': '1h',
        });
    a.onPatch('/scheduled-tasks/t1', (s) => s.reply(200, _task(enabled: false)),
        data: {'enabled': false});
    a.onPost('/scheduled-tasks/t1/run-now', (s) => s.reply(200, _task()));

    final repo = WatchRepository(dio);
    expect((await repo.list()).single.name, '晨报');
    expect(
        (await repo.create(
                name: 'n',
                prompt: 'p',
                agentConfigId: 'a1',
                scheduleKind: 'interval',
                scheduleExpr: '1h'))
            .id,
        't2');
    expect((await repo.setEnabled('t1', false)).enabled, isFalse);
    expect((await repo.runNow('t1')).id, 't1');
  });

  testWidgets('值守中心:列表渲染任务卡(名称/周期/开关)', (tester) async {
    final dio = Dio(BaseOptions(baseUrl: 'http://x/api'));
    DioAdapter(dio: dio)
      ..onGet('/scheduled-tasks', (s) => s.reply(200, [_task()]))
      ..onGet('/sessions', (s) => s.reply(200, const []));
    await tester.pumpWidget(ProviderScope(
      overrides: [dioProvider.overrideWithValue(dio)],
      child: const MaterialApp(home: WatchCenterPage()),
    ));
    await tester.pumpAndSettle();
    expect(find.text('晨报'), findsOneWidget);
    expect(find.textContaining('Cron'), findsOneWidget);
    expect(find.byType(Switch), findsOneWidget);
    expect(find.text('新建值守'), findsOneWidget);
  });

  testWidgets('详情:产出时间线按 scheduled_task_id 关联(深链场景 provider 冷启)', (tester) async {
    final dio = Dio(BaseOptions(baseUrl: 'http://x/api'));
    DioAdapter(dio: dio)
      ..onGet('/scheduled-tasks', (s) => s.reply(200, [_task()]))
      ..onGet(
          '/sessions',
          (s) => s.reply(200, [
                {
                  'id': 's1',
                  'agent_config_id': 'a1',
                  'model': 'm',
                  'title': '晨报 · 7月6日',
                  'status': 'idle',
                  'last_active_at': DateTime.now().toIso8601String(),
                  'scheduled_task_id': 't1',
                },
                {
                  'id': 's2',
                  'agent_config_id': 'a1',
                  'model': 'm',
                  'title': '无关会话',
                  'status': 'idle',
                  'last_active_at': DateTime.now().toIso8601String(),
                },
              ]));
    await tester.pumpWidget(ProviderScope(
      overrides: [dioProvider.overrideWithValue(dio)],
      child: const MaterialApp(home: WatchCenterPage()),
    ));
    await tester.pumpAndSettle();
    await tester.tap(find.text('晨报'));
    await tester.pumpAndSettle();
    expect(find.text('产出记录(1)'), findsOneWidget);
    expect(find.text('晨报 · 7月6日'), findsOneWidget);
    expect(find.text('无关会话'), findsNothing);
  });

  testWidgets('空态引导', (tester) async {
    final dio = Dio(BaseOptions(baseUrl: 'http://x/api'));
    DioAdapter(dio: dio).onGet('/scheduled-tasks', (s) => s.reply(200, const []));
    await tester.pumpWidget(ProviderScope(
      overrides: [dioProvider.overrideWithValue(dio)],
      child: const MaterialApp(home: WatchCenterPage()),
    ));
    await tester.pumpAndSettle();
    expect(find.text('还没有值守任务'), findsOneWidget);
  });
}
