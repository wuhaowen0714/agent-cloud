import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:package_info_plus/package_info_plus.dart';
import 'package:url_launcher/url_launcher.dart';
import '../auth/auth_controller.dart'; // dioProvider

/// 后端 /app/version 返回的最新版本信息。
class AppVersion {
  final String version; // 展示用语义版本,如 1.0.1
  final int build; // 单调递增构建号,用于比对
  final String url; // APK 下载地址
  final bool force; // 强制更新:不可跳过
  final String notes; // 更新说明

  const AppVersion(this.version, this.build, this.url, this.force, this.notes);

  factory AppVersion.fromJson(Map<String, dynamic> j) => AppVersion(
        j['version'] as String,
        (j['build'] as num).toInt(),
        j['url'] as String,
        (j['force'] as bool?) ?? false,
        (j['notes'] as String?) ?? '',
      );
}

/// 检查更新:GET /app/version,build 比当前大则弹窗。
/// - force=true:不可取消(无"稍后"、禁返回键、点外部不关)。
/// - silent=true:无更新/失败时不打扰(启动自动检查用);false 会提示结果(手动检查用)。
Future<void> checkUpdate(BuildContext context, WidgetRef ref,
    {bool silent = true}) async {
  final Dio dio = ref.read(dioProvider);
  final AppVersion latest;
  final int current;
  try {
    final r = await dio.get('/app/version');
    latest = AppVersion.fromJson(r.data as Map<String, dynamic>);
    final info = await PackageInfo.fromPlatform();
    current = int.tryParse(info.buildNumber) ?? 0;
  } catch (e) {
    // /app/version 未部署(404)→ 暂无 OTA 服务,当作无更新,不报错打扰
    final notFound = e is DioException && e.response?.statusCode == 404;
    if (!silent && context.mounted) {
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(
          content: Text(notFound ? '已是最新版本' : '检查更新失败,请稍后重试')));
    }
    return;
  }
  if (latest.build <= current) {
    if (!silent && context.mounted) {
      ScaffoldMessenger.of(context)
          .showSnackBar(const SnackBar(content: Text('已是最新版本')));
    }
    return;
  }
  if (!context.mounted) return;
  await showDialog<void>(
    context: context,
    barrierDismissible: !latest.force,
    builder: (ctx) => PopScope(
      canPop: !latest.force,
      child: AlertDialog(
        title: Text('发现新版本 ${latest.version}'),
        content: Text(latest.notes.isEmpty ? '建议更新到最新版本。' : latest.notes),
        actions: [
          if (!latest.force)
            TextButton(
                onPressed: () => Navigator.pop(ctx), child: const Text('稍后')),
          FilledButton(
            onPressed: () async {
              await launchUrl(Uri.parse(latest.url),
                  mode: LaunchMode.externalApplication);
              if (!latest.force && ctx.mounted) Navigator.pop(ctx);
            },
            child: const Text('立即更新'),
          ),
        ],
      ),
    ),
  );
}
