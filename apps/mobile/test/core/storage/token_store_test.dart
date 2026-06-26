import 'package:flutter_test/flutter_test.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:agent_cloud_mobile/core/storage/token_store.dart';

void main() {
  setUp(() => FlutterSecureStorage.setMockInitialValues({}));

  test('save / read / clear', () async {
    final store = TokenStore(const FlutterSecureStorage());
    await store.save(access: 'a1', refresh: 'r1');
    expect(await store.access(), 'a1');
    expect(await store.refresh(), 'r1');
    await store.clear();
    expect(await store.access(), isNull);
    expect(await store.refresh(), isNull);
  });

  test('save 期间发起的 access read 不覆盖新 token(race 回归)', () async {
    // 新装登录 race:access() 读空 storage 挂在 await,期间 save 写入 token。
    // 那次 stale read 完成后绝不能把 token 覆盖回 null(旧 `??= await` 写法的 bug)。
    final store = TokenStore(const FlutterSecureStorage());
    final pending = store.access(); // 读空 storage,挂起在 await
    await store.save(access: 'A', refresh: 'R'); // 期间写入 token
    expect(await pending, 'A'); // 必须返回 A,不能被 stale read 覆盖成 null
  });
}
