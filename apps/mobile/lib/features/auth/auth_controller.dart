import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import '../../core/storage/token_store.dart';
import '../../core/api/dio_client.dart';
import '../../models/user.dart';
import 'auth_repository.dart';

final tokenStoreProvider =
    Provider((_) => TokenStore(const FlutterSecureStorage()));
final dioProvider = Provider((ref) => buildDio(ref.read(tokenStoreProvider)));
final authRepoProvider = Provider(
    (ref) => AuthRepository(ref.read(dioProvider), ref.read(tokenStoreProvider)));

/// 登录态:null = 未登录;User = 已登录。loading = bootstrap(启动探 me)/登录中。
class AuthController extends AsyncNotifier<User?> {
  @override
  Future<User?> build() => ref.read(authRepoProvider).me();

  Future<void> login(String email, String pw) async {
    state = const AsyncValue.loading();
    state = await AsyncValue.guard<User?>(
        () => ref.read(authRepoProvider).login(email, pw));
  }

  Future<void> register(String email, String pw) async {
    state = const AsyncValue.loading();
    state = await AsyncValue.guard<User?>(
        () => ref.read(authRepoProvider).register(email, pw));
  }

  Future<void> logout() async {
    await ref.read(authRepoProvider).logout();
    state = const AsyncValue.data(null);
  }
}

final authControllerProvider =
    AsyncNotifierProvider<AuthController, User?>(AuthController.new);
