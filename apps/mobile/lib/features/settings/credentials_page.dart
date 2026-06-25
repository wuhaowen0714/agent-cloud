import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../../core/theme/app_theme.dart';
import '../../models/credential.dart';
import 'settings_repository.dart';

final credentialsProvider =
    FutureProvider.autoDispose<List<ProviderCredential>>(
        (ref) => ref.read(settingsRepoProvider).listCredentials());

/// BYOK:用户自带 OpenAI 兼容 API Key,会话可选用其中的模型。
class CredentialsPage extends ConsumerWidget {
  const CredentialsPage({super.key});

  Future<void> _add(BuildContext context, WidgetRef ref) async {
    final created = await showModalBottomSheet<bool>(
      context: context,
      isScrollControlled: true,
      shape: const RoundedRectangleBorder(
          borderRadius: BorderRadius.vertical(top: Radius.circular(20))),
      builder: (_) => const _AddCredentialSheet(),
    );
    if (created == true) ref.invalidate(credentialsProvider);
  }

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final creds = ref.watch(credentialsProvider);
    return Scaffold(
      appBar: AppBar(title: const Text('API 凭据')),
      floatingActionButton: FloatingActionButton.extended(
        onPressed: () => _add(context, ref),
        icon: const Icon(Icons.add),
        label: const Text('新增'),
      ),
      body: creds.when(
        loading: () => const Center(child: CircularProgressIndicator()),
        error: (e, _) => Center(child: Text('加载失败: $e')),
        data: (list) => list.isEmpty
            ? _empty()
            : ListView.builder(
                padding: const EdgeInsets.fromLTRB(12, 12, 12, 88),
                itemCount: list.length,
                itemBuilder: (_, i) => _tile(context, ref, list[i]),
              ),
      ),
    );
  }

  Widget _empty() => const Center(
        child: Padding(
          padding: EdgeInsets.all(32),
          child: Column(mainAxisSize: MainAxisSize.min, children: [
            Icon(Icons.key_outlined, size: 40, color: AppTheme.faint),
            SizedBox(height: 12),
            Text('还没有自定义凭据',
                style: TextStyle(
                    fontSize: 15,
                    fontWeight: FontWeight.w600,
                    color: AppTheme.ink)),
            SizedBox(height: 6),
            Text('添加你自己的 OpenAI 兼容 API Key,\n会话即可选用其中的模型',
                textAlign: TextAlign.center,
                style: TextStyle(color: AppTheme.muted, fontSize: 13)),
          ]),
        ),
      );

  Widget _tile(BuildContext context, WidgetRef ref, ProviderCredential c) =>
      Container(
        margin: const EdgeInsets.only(bottom: 10),
        padding: const EdgeInsets.all(14),
        decoration: BoxDecoration(
          color: AppTheme.surface,
          borderRadius: BorderRadius.circular(AppTheme.rCard),
          border: Border.all(color: AppTheme.border),
        ),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Row(children: [
            Expanded(
              child: Text(c.name,
                  style: const TextStyle(
                      fontWeight: FontWeight.w600,
                      fontSize: 15,
                      color: AppTheme.ink)),
            ),
            IconButton(
              padding: EdgeInsets.zero,
              constraints: const BoxConstraints(),
              icon: const Icon(Icons.delete_outline,
                  size: 20, color: AppTheme.faint),
              onPressed: () async {
                await ref.read(settingsRepoProvider).deleteCredential(c.id);
                ref.invalidate(credentialsProvider);
              },
            ),
          ]),
          const SizedBox(height: 4),
          Text(c.baseUrl,
              style: const TextStyle(fontSize: 12.5, color: AppTheme.muted)),
          Text(c.masked,
              style: const TextStyle(
                  fontSize: 12,
                  color: AppTheme.faint,
                  fontFamily: 'monospace')),
          if (c.models.isNotEmpty) ...[
            const SizedBox(height: 8),
            Wrap(
              spacing: 6,
              runSpacing: 6,
              children: c.models
                  .map((m) => Container(
                        padding: const EdgeInsets.symmetric(
                            horizontal: 8, vertical: 3),
                        decoration: BoxDecoration(
                          color: AppTheme.tealSoft,
                          borderRadius: BorderRadius.circular(AppTheme.rChip),
                        ),
                        child: Text(m,
                            style: const TextStyle(
                                fontSize: 11.5, color: AppTheme.tealDark)),
                      ))
                  .toList(),
            ),
          ],
        ]),
      );
}

class _AddCredentialSheet extends ConsumerStatefulWidget {
  const _AddCredentialSheet();
  @override
  ConsumerState<_AddCredentialSheet> createState() =>
      _AddCredentialSheetState();
}

class _AddCredentialSheetState extends ConsumerState<_AddCredentialSheet> {
  final _name = TextEditingController();
  final _baseUrl = TextEditingController();
  final _apiKey = TextEditingController();
  final _models = TextEditingController();
  bool _saving = false;
  String? _error;

  @override
  void dispose() {
    _name.dispose();
    _baseUrl.dispose();
    _apiKey.dispose();
    _models.dispose();
    super.dispose();
  }

  Future<void> _submit() async {
    final name = _name.text.trim();
    final baseUrl = _baseUrl.text.trim();
    final apiKey = _apiKey.text.trim();
    final models = _models.text
        .split(',')
        .map((s) => s.trim())
        .where((s) => s.isNotEmpty)
        .toList();
    if (name.isEmpty || baseUrl.isEmpty || apiKey.isEmpty || models.isEmpty) {
      setState(() => _error = '请填写全部字段(模型用逗号分隔)');
      return;
    }
    setState(() {
      _saving = true;
      _error = null;
    });
    try {
      await ref.read(settingsRepoProvider).createCredential(
          name: name, baseUrl: baseUrl, apiKey: apiKey, models: models);
      if (mounted) Navigator.pop(context, true);
    } catch (e) {
      if (mounted) {
        setState(() {
          _saving = false;
          _error = '创建失败: $e';
        });
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: EdgeInsets.only(
        left: 20,
        right: 20,
        top: 20,
        bottom: MediaQuery.of(context).viewInsets.bottom + 20,
      ),
      child: Column(mainAxisSize: MainAxisSize.min, children: [
        const Align(
          alignment: Alignment.centerLeft,
          child: Text('新增 API 凭据',
              style: TextStyle(
                  fontSize: 17,
                  fontWeight: FontWeight.w600,
                  color: AppTheme.ink)),
        ),
        const SizedBox(height: 16),
        TextField(
          controller: _name,
          decoration: const InputDecoration(hintText: '名称,如 OpenRouter'),
        ),
        const SizedBox(height: 12),
        TextField(
          controller: _baseUrl,
          decoration:
              const InputDecoration(hintText: 'Base URL,如 https://...'),
          keyboardType: TextInputType.url,
        ),
        const SizedBox(height: 12),
        TextField(
          controller: _apiKey,
          decoration: const InputDecoration(hintText: 'API Key'),
          obscureText: true,
        ),
        const SizedBox(height: 12),
        TextField(
          controller: _models,
          decoration: const InputDecoration(
              hintText: '模型(逗号分隔),如 gpt-4o, claude-3.5'),
        ),
        if (_error != null) ...[
          const SizedBox(height: 12),
          Text(_error!,
              style: const TextStyle(color: AppTheme.danger, fontSize: 13)),
        ],
        const SizedBox(height: 18),
        SizedBox(
          width: double.infinity,
          child: FilledButton(
            onPressed: _saving ? null : _submit,
            child: Text(_saving ? '创建中…' : '创建'),
          ),
        ),
      ]),
    );
  }
}
