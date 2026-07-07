import 'package:flutter/material.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';

import '../../core/push/push_service.dart';
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
          _section('通知', const [_PushToggleTile()]),
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

/// 「后台推送」开关:开=请求通知权限 + 启动前台服务(WS 长连,AI 主动提醒/定时任务结果
/// 推到系统通知);关=停服务。状态存 secure_storage,app 启动时按它自动拉起(main.dart)。
class _PushToggleTile extends StatefulWidget {
  const _PushToggleTile();
  @override
  State<_PushToggleTile> createState() => _PushToggleTileState();
}

class _PushToggleTileState extends State<_PushToggleTile> {
  static const _storage = FlutterSecureStorage();
  bool _enabled = false;
  bool _busy = false;

  @override
  void initState() {
    super.initState();
    _storage.read(key: kPushEnabledKey).then((v) {
      if (mounted) setState(() => _enabled = v == 'true');
    });
  }

  Future<void> _toggle(bool on) async {
    if (_busy) return;
    setState(() => _busy = true);
    try {
      if (on) {
        final granted = await requestNotificationPermission();
        if (!granted && mounted) {
          ScaffoldMessenger.of(context).showSnackBar(const SnackBar(
              content: Text('需要通知权限才能推送,请在系统设置中允许')));
        }
        await startPushService();
        // 系统级电池豁免对话框(Doze/冻结致息屏断连的主修复,一键允许)
        await requestBatteryExemption();
        await _storage.write(key: kPushEnabledKey, value: 'true');
        if (mounted) {
          setState(() => _enabled = true);
          // 国产 ROM 杀后台狠:引导一次性设置(不设的话息屏后网络被掐、连接秒死,
          // 提醒只能等下次打开 app 补送 —— 2026-07-07 实测 ColorOS 如此)
          showDialog<void>(
            context: context,
            builder: (c) => AlertDialog(
              title: const Text('保持推送在线'),
              content: const Text(
                  '刚才如果弹了「忽略电池优化」请选允许。另外请在系统设置中给本应用开启:\n\n'
                  '① 自启动\n'
                  '② 耗电管理 → 允许完全后台行为(ColorOS)\n\n'
                  '路径:设置 → 应用管理 → Agent Cloud。不开的话息屏后系统会掐断连接,'
                  '提醒要等下次打开 app 才补送。'),
              actions: [
                TextButton(
                    onPressed: () => Navigator.pop(c),
                    child: const Text('知道了')),
              ],
            ),
          );
        }
      } else {
        await stopPushService();
        await _storage.write(key: kPushEnabledKey, value: 'false');
        if (mounted) setState(() => _enabled = false);
      }
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) => ListTile(
        leading: const Icon(Icons.notifications_active_outlined,
            color: AppTheme.teal),
        title: const Text('后台推送',
            style: TextStyle(fontSize: 15, color: AppTheme.ink)),
        subtitle: const Text('AI 主动提醒与定时任务结果推送到系统通知(常驻一条低优先级通知保持连接)',
            style: TextStyle(fontSize: 12, color: AppTheme.muted)),
        trailing: Switch(value: _enabled, onChanged: _busy ? null : _toggle),
      );
}
