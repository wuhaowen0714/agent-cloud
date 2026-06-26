import 'package:dio/dio.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:http_mock_adapter/http_mock_adapter.dart';
import 'package:agent_cloud_mobile/features/auth/auth_controller.dart'; // dioProvider
import 'package:agent_cloud_mobile/features/sessions/sessions_controller.dart';

Map<String, dynamic> _session(String id, String model, {String title = 'hi'}) => {
      'id': id,
      'agent_config_id': 'a1',
      'model': model,
      'title': title,
      'status': 'idle',
    };

void main() {
  // 根因回归:首回合 _pollTitle 的全量 refresh 拿到旧 DB 快照(model 还是切换前的值),
  // 不能覆盖前端刚 patchModel 的 model —— 否则"切回文本后再发图不再自动切 vision"。
  test('refresh 保留前端权威 model,不被 DB 旧快照覆盖', () async {
    final dio = Dio(BaseOptions(baseUrl: 'http://x/api'));
    final adapter = DioAdapter(dio: dio);
    // GET /sessions 始终返回 model=A(模拟 refresh 派发时读到的、patchModel 之前的旧快照)。
    adapter.onGet('/sessions', (s) => s.reply(200, [_session('s1', 'A')]));
    // 用户切到 B:PATCH 返回 model=B。
    adapter.onPatch('/sessions/s1',
        (s) => s.reply(200, _session('s1', 'B')),
        data: {'model': 'B'});

    final container = ProviderContainer(
        overrides: [dioProvider.overrideWithValue(dio)]);
    addTearDown(container.dispose);

    // build → state=[s1 model=A]
    await container.read(sessionsControllerProvider.future);
    final ctrl = container.read(sessionsControllerProvider.notifier);

    // 切到 B(落库 + 更新前端权威)
    await ctrl.patchModel('s1', 'B');
    expect(
        container.read(sessionsControllerProvider).asData!.value.first.model, 'B');

    // 并发轮询触发的 refresh 拿到旧快照 A —— 必须保留本地 B,不被覆盖。
    await ctrl.refresh();
    expect(
      container.read(sessionsControllerProvider).asData!.value.first.model,
      'B',
      reason: 'refresh 不应用 DB 旧快照 model 覆盖前端刚切的 model(vision 自动切换竞态根因)',
    );
  });

  // refresh 合并按会话粒度:只把切过的那条保留本地 model,其它会话不受影响、保持服务器值。
  test('refresh 多会话各自保留本地 model,互不干扰', () async {
    final dio = Dio(BaseOptions(baseUrl: 'http://x/api'));
    final adapter = DioAdapter(dio: dio);
    adapter.onGet('/sessions',
        (s) => s.reply(200, [_session('s1', 'A'), _session('s2', 'C')]));
    adapter.onPatch('/sessions/s1',
        (s) => s.reply(200, _session('s1', 'B')), data: {'model': 'B'});

    final container = ProviderContainer(
        overrides: [dioProvider.overrideWithValue(dio)]);
    addTearDown(container.dispose);

    await container.read(sessionsControllerProvider.future);
    final ctrl = container.read(sessionsControllerProvider.notifier);
    await ctrl.patchModel('s1', 'B'); // 只切 s1
    await ctrl.refresh();

    final list = container.read(sessionsControllerProvider).asData!.value;
    expect(list.firstWhere((s) => s.id == 's1').model, 'B'); // 切过的保留本地
    expect(list.firstWhere((s) => s.id == 's2').model, 'C'); // 没切的保持服务器值
  });
}
