import 'dart:async';
import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:ota_update/ota_update.dart';
import 'package:package_info_plus/package_info_plus.dart';
import 'package:url_launcher/url_launcher.dart';
import '../auth/auth_controller.dart'; // dioProvider

/// 后端 /app/version 返回的最新版本信息。
class AppVersion {
  final String version;
  final int build;
  final String url;
  final bool force;
  final String notes;

  const AppVersion(this.version, this.build, this.url, this.force, this.notes);

  factory AppVersion.fromJson(Map<String, dynamic> j) => AppVersion(
        j['version'] as String,
        (j['build'] as num).toInt(),
        j['url'] as String,
        (j['force'] as bool?) ?? false,
        (j['notes'] as String?) ?? '',
      );
}

/// 检查更新:build 比当前大则弹窗。force=true 不可跳过;silent=true 无更新/失败不打扰。
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
    // /app/version 未部署(404)→ 当作无更新,不报错打扰
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
            onPressed: () {
              Navigator.pop(ctx); // 关版本提示
              _runInAppUpdate(context, latest.url); // app 内下载 + 安装
            },
            child: const Text('立即更新'),
          ),
        ],
      ),
    ),
  );
}

/// app 内下载 + 直接拉起系统安装器(ota_update),进度对话框。
void _runInAppUpdate(BuildContext context, String url) {
  showDialog<void>(
    context: context,
    barrierDismissible: false,
    builder: (_) => _OtaProgressDialog(url),
  );
}

class _OtaProgressDialog extends StatefulWidget {
  final String url;
  const _OtaProgressDialog(this.url);
  @override
  State<_OtaProgressDialog> createState() => _OtaProgressDialogState();
}

class _OtaProgressDialogState extends State<_OtaProgressDialog> {
  double _pct = 0;
  String _msg = '准备下载…';
  bool _ended = false; // 失败/已触发安装 → 可关闭
  StreamSubscription<OtaEvent>? _sub;

  @override
  void initState() {
    super.initState();
    _start();
  }

  void _start() {
    try {
      // 下载文件名带 build 号(取 url 末段),而非固定 'agent-cloud-update.apk'。
      // 固定名在部分 ROM 上会被安装器/旧 session 缓存,装回设备上残留的旧包
      // (现象:更新后版本号没变、提示"已安装相同版本")。唯一文件名确保装的是本次下载的新包。
      final seg = Uri.parse(widget.url).pathSegments;
      final apkName = (seg.isNotEmpty && seg.last.toLowerCase().endsWith('.apk'))
          ? seg.last
          : 'agent-cloud-update.apk';
      _sub = OtaUpdate()
          .execute(widget.url, destinationFilename: apkName)
          .listen(
        (e) {
          if (!mounted) return;
          switch (e.status) {
            case OtaStatus.DOWNLOADING:
              setState(() {
                _pct = double.tryParse(e.value ?? '') ?? _pct;
                _msg = '下载中 ${_pct.toStringAsFixed(0)}%';
              });
            case OtaStatus.INSTALLING:
              setState(() {
                _ended = true; // 安装界面已拉起,允许关对话框
                _msg = '下载完成,正在拉起安装…';
              });
            default:
              setState(() {
                _ended = true;
                _msg = '更新失败(${e.status.name}),可改用浏览器下载';
              });
          }
        },
        onError: (_) {
          if (mounted) {
            setState(() {
              _ended = true;
              _msg = '更新失败,可改用浏览器下载';
            });
          }
        },
      );
    } catch (_) {
      setState(() {
        _ended = true;
        _msg = '更新失败,可改用浏览器下载';
      });
    }
  }

  @override
  void dispose() {
    _sub?.cancel();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return PopScope(
      canPop: _ended, // 下载中禁止关
      child: AlertDialog(
        title: const Text('更新'),
        content: Column(mainAxisSize: MainAxisSize.min, children: [
          if (!_ended)
            LinearProgressIndicator(value: _pct > 0 ? _pct / 100 : null),
          const SizedBox(height: 14),
          Text(_msg),
        ]),
        actions: _ended
            ? [
                TextButton(
                  onPressed: () => launchUrl(Uri.parse(widget.url),
                      mode: LaunchMode.externalApplication),
                  child: const Text('浏览器下载'),
                ),
                TextButton(
                    onPressed: () => Navigator.pop(context),
                    child: const Text('关闭')),
              ]
            : null,
      ),
    );
  }
}
