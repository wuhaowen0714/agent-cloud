import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:package_info_plus/package_info_plus.dart';
import '../../core/theme/app_theme.dart';
import '../auth/auth_controller.dart';
import '../update/update_service.dart';

class SettingsPage extends ConsumerWidget {
  const SettingsPage({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final user = ref.watch(authControllerProvider).asData?.value;
    return Scaffold(
      appBar: AppBar(title: const Text('设置')),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          // 账号卡
          Container(
            padding: const EdgeInsets.all(16),
            decoration: BoxDecoration(
              color: AppTheme.surface,
              borderRadius: BorderRadius.circular(AppTheme.rCard),
              border: Border.all(color: AppTheme.border),
            ),
            child: Row(children: [
              CircleAvatar(
                radius: 24,
                backgroundColor: AppTheme.tealSoft,
                child: Text(
                  (user?.email ?? '?').substring(0, 1).toUpperCase(),
                  style: const TextStyle(
                      color: AppTheme.teal,
                      fontWeight: FontWeight.w700,
                      fontSize: 20),
                ),
              ),
              const SizedBox(width: 14),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(user?.email ?? '-',
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                        style: const TextStyle(
                            fontSize: 15,
                            fontWeight: FontWeight.w600,
                            color: AppTheme.ink)),
                    const SizedBox(height: 2),
                    const Text('已登录',
                        style:
                            TextStyle(fontSize: 12.5, color: AppTheme.muted)),
                  ],
                ),
              ),
            ]),
          ),
          const SizedBox(height: 20),
          _section('配置', [
            _navTile(context, Icons.key_outlined, 'API 凭据', '管理自带的 API Key',
                '/settings/credentials'),
            _navTile(context, Icons.psychology_outlined, '记忆',
                '智能体记住的关于你的信息', '/settings/memory'),
            _navTile(context, Icons.extension_outlined, '技能', '已安装的技能',
                '/settings/skills'),
          ]),
          const SizedBox(height: 20),
          _section('关于', const [_AboutTile()]),
          const SizedBox(height: 20),
          // 登出
          Container(
            decoration: BoxDecoration(
              color: AppTheme.surface,
              borderRadius: BorderRadius.circular(AppTheme.rCard),
              border: Border.all(color: AppTheme.border),
            ),
            child: ListTile(
              shape: RoundedRectangleBorder(
                  borderRadius: BorderRadius.circular(AppTheme.rCard)),
              leading: const Icon(Icons.logout, color: AppTheme.danger),
              title: const Text('登出',
                  style: TextStyle(
                      color: AppTheme.danger, fontWeight: FontWeight.w500)),
              onTap: () => ref.read(authControllerProvider.notifier).logout(),
            ),
          ),
        ],
      ),
    );
  }

  Widget _section(String title, List<Widget> tiles) => Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Padding(
            padding: const EdgeInsets.only(left: 4, bottom: 8),
            child: Text(title,
                style: const TextStyle(
                    fontSize: 13,
                    fontWeight: FontWeight.w600,
                    color: AppTheme.muted)),
          ),
          Container(
            decoration: BoxDecoration(
              color: AppTheme.surface,
              borderRadius: BorderRadius.circular(AppTheme.rCard),
              border: Border.all(color: AppTheme.border),
            ),
            child: Column(children: _withDividers(tiles)),
          ),
        ],
      );

  List<Widget> _withDividers(List<Widget> tiles) {
    final out = <Widget>[];
    for (var i = 0; i < tiles.length; i++) {
      out.add(tiles[i]);
      if (i < tiles.length - 1) {
        out.add(const Divider(height: 1, indent: 52));
      }
    }
    return out;
  }

  Widget _navTile(BuildContext context, IconData icon, String title,
          String subtitle, String route) =>
      ListTile(
        leading: Icon(icon, color: AppTheme.teal),
        title: Text(title,
            style: const TextStyle(
                fontWeight: FontWeight.w500, color: AppTheme.ink)),
        subtitle: Text(subtitle,
            style: const TextStyle(fontSize: 12.5, color: AppTheme.muted)),
        trailing: const Icon(Icons.chevron_right, color: AppTheme.faint),
        onTap: () => context.push(route),
      );
}

class _AboutTile extends ConsumerWidget {
  const _AboutTile();
  @override
  Widget build(BuildContext context, WidgetRef ref) =>
      FutureBuilder<PackageInfo>(
        future: PackageInfo.fromPlatform(),
        builder: (_, snap) => ListTile(
          leading: const Icon(Icons.info_outline, color: AppTheme.teal),
          title: const Text('版本',
              style: TextStyle(
                  fontWeight: FontWeight.w500, color: AppTheme.ink)),
          subtitle: Text(
              snap.hasData
                  ? '${snap.data!.version} (${snap.data!.buildNumber})'
                  : '…',
              style: const TextStyle(fontSize: 12.5, color: AppTheme.muted)),
          trailing: TextButton(
            onPressed: () => checkUpdate(context, ref, silent: false),
            child: const Text('检查更新'),
          ),
        ),
      );
}
