import 'package:dio/dio.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http_mock_adapter/http_mock_adapter.dart';
import 'package:agent_cloud_mobile/features/settings/settings_repository.dart';

void main() {
  test('listCredentials 解析(脱敏 key + 模型)', () async {
    final dio = Dio(BaseOptions(baseUrl: 'http://x/api'));
    DioAdapter(dio: dio).onGet(
      '/credentials',
      (s) => s.reply(200, [
        {
          'id': 'c1',
          'name': 'OpenRouter',
          'base_url': 'https://or/v1',
          'masked': 'sk-…1234',
          'models': ['gpt-4o', 'claude-3.5'],
          'created_at': '2026-01-01',
        },
      ]),
    );
    final creds = await SettingsRepository(dio).listCredentials();
    expect(creds.single.name, 'OpenRouter');
    expect(creds.single.masked, 'sk-…1234');
    expect(creds.single.models, ['gpt-4o', 'claude-3.5']);
  });

  test('createCredential POST 携带字段', () async {
    final dio = Dio(BaseOptions(baseUrl: 'http://x/api'));
    DioAdapter(dio: dio).onPost(
      '/credentials',
      (s) => s.reply(201, {'id': 'c2'}),
      data: {
        'name': 'n',
        'base_url': 'u',
        'api_key': 'k',
        'models': ['m1'],
      },
    );
    // 不抛即通过(repo 不解析返回)
    await SettingsRepository(dio).createCredential(
        name: 'n', baseUrl: 'u', apiKey: 'k', models: ['m1']);
  });

  test('getMemory 取 content', () async {
    final dio = Dio(BaseOptions(baseUrl: 'http://x/api'));
    DioAdapter(dio: dio).onGet(
      '/memory',
      (s) => s.reply(200, {
        'scope': 'user',
        'owner_id': 'u1',
        'content': '记住的内容',
        'version': 1,
      }),
      queryParameters: {'scope': 'user'},
    );
    final mem = await SettingsRepository(dio).getMemory();
    expect(mem, '记住的内容');
  });

  test('listSkills 解析', () async {
    final dio = Dio(BaseOptions(baseUrl: 'http://x/api'));
    DioAdapter(dio: dio).onGet(
      '/skills',
      (s) => s.reply(200, [
        {
          'id': 'sk1',
          'user_id': 'u1',
          'name': 'web_search',
          'description': '联网搜索',
          'source': 'builtin',
          'version': '1.0',
        },
      ]),
    );
    final skills = await SettingsRepository(dio).listSkills();
    expect(skills.single.name, 'web_search');
    expect(skills.single.source, 'builtin');
  });
}
