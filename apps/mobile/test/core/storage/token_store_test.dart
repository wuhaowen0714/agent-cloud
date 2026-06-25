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
}
