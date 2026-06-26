import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:web_socket_channel/io.dart';
import 'package:web_socket_channel/web_socket_channel.dart';
import 'package:xterm/xterm.dart';
import '../../core/api/dio_client.dart'; // kBaseUrl
import '../../core/theme/app_theme.dart';
import '../auth/auth_controller.dart'; // tokenStoreProvider

/// 工作区终端:PTY-over-WebSocket。
/// - 下行二进制 = PTY 输出 → terminal.write
/// - terminal.onOutput(键盘)→ 二进制上行;onResize → 文本帧 {rows,cols}
/// - 鉴权:token 走 subprotocol ["bearer", access](WS 不能带 header)
class TerminalPage extends ConsumerStatefulWidget {
  const TerminalPage({super.key});
  @override
  ConsumerState<TerminalPage> createState() => _TerminalPageState();
}

class _TerminalPageState extends ConsumerState<TerminalPage> {
  final _terminal = Terminal(maxLines: 10000);
  WebSocketChannel? _ch;
  String _status = '连接中…';

  @override
  void initState() {
    super.initState();
    _connect();
  }

  String _wsUrl() {
    var u = kBaseUrl;
    if (u.startsWith('https://')) {
      u = 'wss://${u.substring(8)}';
    } else if (u.startsWith('http://')) {
      u = 'ws://${u.substring(7)}';
    }
    return '$u/terminal';
  }

  Future<void> _connect() async {
    setState(() => _status = '连接中…');
    final token = await ref.read(tokenStoreProvider).access();
    if (token == null) {
      if (mounted) setState(() => _status = '未登录');
      return;
    }
    try {
      final ch = IOWebSocketChannel.connect(
        Uri.parse(_wsUrl()),
        protocols: ['bearer', token],
      );
      _ch = ch;
      _terminal.onOutput = (data) => ch.sink.add(utf8.encode(data));
      _terminal.onResize =
          (w, h, pw, ph) => ch.sink.add(jsonEncode({'rows': h, 'cols': w}));
      ch.stream.listen(
        (msg) {
          if (msg is List<int>) {
            _terminal.write(utf8.decode(msg, allowMalformed: true));
          } else if (msg is String) {
            _terminal.write(msg);
          }
        },
        onDone: () {
          if (mounted) setState(() => _status = '已断开');
        },
        onError: (_) {
          if (mounted) setState(() => _status = '连接错误');
        },
      );
      if (mounted) setState(() => _status = '');
    } catch (e) {
      if (mounted) setState(() => _status = '连接失败');
    }
  }

  void _reconnect() {
    _ch?.sink.close();
    _connect();
  }

  @override
  void dispose() {
    _ch?.sink.close();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('终端'),
        actions: [
          if (_status.isNotEmpty)
            Padding(
              padding: const EdgeInsets.only(right: 8),
              child: Center(
                  child: Text(_status,
                      style: const TextStyle(
                          fontSize: 12, color: AppTheme.muted))),
            ),
          IconButton(
              icon: const Icon(Icons.refresh),
              tooltip: '重连',
              onPressed: _reconnect),
        ],
      ),
      body: SafeArea(
        child: TerminalView(_terminal, autofocus: true),
      ),
    );
  }
}
