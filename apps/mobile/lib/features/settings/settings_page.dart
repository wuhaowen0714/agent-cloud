import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:package_info_plus/package_info_plus.dart';
import '../auth/auth_controller.dart';
import '../update/update_service.dart';

class SettingsPage extends ConsumerWidget {
  const SettingsPage({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final user = ref.watch(authControllerProvider).asData?.value;
    return Scaffold(
      appBar: AppBar(title: const Text('设置')),
      body: ListView(children: [
        ListTile(
          leading: const Icon(Icons.person_outline),
          title: const Text('账号'),
          subtitle: Text(user?.email ?? '-'),
        ),
        FutureBuilder<PackageInfo>(
          future: PackageInfo.fromPlatform(),
          builder: (_, snap) => ListTile(
            leading: const Icon(Icons.info_outline),
            title: const Text('版本'),
            subtitle: Text(snap.hasData
                ? '${snap.data!.version} (${snap.data!.buildNumber})'
                : '…'),
            trailing: TextButton(
              onPressed: () => checkUpdate(context, ref, silent: false),
              child: const Text('检查更新'),
            ),
          ),
        ),
        const Divider(),
        ListTile(
          leading: const Icon(Icons.logout, color: Colors.red),
          title: const Text('登出', style: TextStyle(color: Colors.red)),
          onTap: () => ref.read(authControllerProvider.notifier).logout(),
        ),
      ]),
    );
  }
}
