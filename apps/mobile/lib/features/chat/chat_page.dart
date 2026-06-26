import 'dart:io';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:image_picker/image_picker.dart';
import '../../core/theme/app_theme.dart';
import '../files/files_repository.dart';
import '../sessions/sessions_controller.dart';
import 'chat_controller.dart';
import 'model_picker.dart';
import 'turn_blocks.dart';

class ChatPage extends ConsumerStatefulWidget {
  final String sessionId;
  const ChatPage(this.sessionId, {super.key});
  @override
  ConsumerState<ChatPage> createState() => _ChatPageState();
}

class _ChatPageState extends ConsumerState<ChatPage> {
  final _input = TextEditingController();
  final _scroll = ScrollController();
  final List<XFile> _pending = []; // 待发图片
  bool _uploading = false;

  @override
  void dispose() {
    _input.dispose();
    _scroll.dispose();
    super.dispose();
  }

  Future<void> _pickImages() async {
    final imgs = await ImagePicker().pickMultiImage();
    if (imgs.isNotEmpty && mounted) setState(() => _pending.addAll(imgs));
  }

  Future<void> _send() async {
    final text = _input.text.trim();
    if (text.isEmpty && _pending.isEmpty) return;
    var paths = <String>[];
    if (_pending.isNotEmpty) {
      setState(() => _uploading = true);
      try {
        paths = await ref.read(filesRepoProvider).uploadImages(_pending);
      } catch (e) {
        if (!mounted) return;
        setState(() => _uploading = false);
        ScaffoldMessenger.of(context)
            .showSnackBar(SnackBar(content: Text('图片上传失败: $e')));
        return; // 保留待发图片,可重试
      }
      if (!mounted) return;
      setState(() => _uploading = false);
    }
    _input.clear();
    setState(() => _pending.clear());
    ref
        .read(chatControllerProvider(widget.sessionId).notifier)
        .send(text, images: paths);
  }

  String? _agentId() {
    final sessions = ref.read(sessionsControllerProvider).asData?.value ?? [];
    final m = sessions.where((s) => s.id == widget.sessionId);
    return m.isEmpty ? null : m.first.agentConfigId;
  }

  void _onMenu(String v) {
    // 文件/终端是工作区级,工具/技能是 agent 级
    if (v == 'files') {
      context.push('/files');
      return;
    }
    if (v == 'terminal') {
      context.push('/terminal');
      return;
    }
    final aid = _agentId();
    if (aid == null) {
      ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('会话信息未加载,请返回列表再进')));
      return;
    }
    switch (v) {
      case 'tools':
        context.push('/agent/$aid/tools');
      case 'skills':
        context.push('/agent/$aid/skills');
    }
  }

  Future<void> _renameSession(String current) async {
    final ctrl = TextEditingController(
        text: (current == '对话' || current == '新会话') ? '' : current);
    final title = await showDialog<String>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('重命名会话'),
        content: TextField(
          controller: ctrl,
          autofocus: true,
          decoration: const InputDecoration(hintText: '会话标题'),
          onSubmitted: (v) => Navigator.pop(ctx, v.trim()),
        ),
        actions: [
          TextButton(
              onPressed: () => Navigator.pop(ctx), child: const Text('取消')),
          FilledButton(
              onPressed: () => Navigator.pop(ctx, ctrl.text.trim()),
              child: const Text('保存')),
        ],
      ),
    );
    ctrl.dispose();
    if (title != null && title.isNotEmpty) {
      await ref
          .read(sessionsControllerProvider.notifier)
          .rename(widget.sessionId, title);
    }
  }

  @override
  Widget build(BuildContext context) {
    final state = ref.watch(chatControllerProvider(widget.sessionId));
    // session 标题(可改):从会话列表取,rename 后自动更新
    final sessions =
        ref.watch(sessionsControllerProvider).asData?.value ?? const [];
    final match = sessions.where((s) => s.id == widget.sessionId);
    final title = match.isEmpty ? '对话' : match.first.displayTitle;
    // 新内容到达时滚到底部(跟随生成 / 进会话定位到最新)
    ref.listen(chatControllerProvider(widget.sessionId), (_, _) {
      WidgetsBinding.instance.addPostFrameCallback((_) {
        if (_scroll.hasClients) {
          _scroll.jumpTo(_scroll.position.maxScrollExtent);
        }
      });
    });
    return Scaffold(
      appBar: AppBar(
        title: GestureDetector(
          onTap: () => _renameSession(title),
          child: Row(mainAxisSize: MainAxisSize.min, children: [
            Flexible(
                child: Text(title,
                    overflow: TextOverflow.ellipsis,
                    style: const TextStyle(fontSize: 17))),
            const SizedBox(width: 5),
            const Icon(Icons.edit_outlined, size: 15, color: AppTheme.faint),
          ]),
        ),
        actions: [
          IconButton(
            icon: const Icon(Icons.tune),
            tooltip: '切换模型',
            onPressed: () => showModelPicker(context, ref, widget.sessionId),
          ),
          PopupMenuButton<String>(
            tooltip: '更多',
            onSelected: _onMenu,
            itemBuilder: (_) => const [
              PopupMenuItem(
                  value: 'tools',
                  child: ListTile(
                      leading: Icon(Icons.build_outlined),
                      title: Text('工具'),
                      contentPadding: EdgeInsets.zero)),
              PopupMenuItem(
                  value: 'skills',
                  child: ListTile(
                      leading: Icon(Icons.extension_outlined),
                      title: Text('技能'),
                      contentPadding: EdgeInsets.zero)),
              PopupMenuItem(
                  value: 'files',
                  child: ListTile(
                      leading: Icon(Icons.folder_outlined),
                      title: Text('文件'),
                      contentPadding: EdgeInsets.zero)),
              PopupMenuItem(
                  value: 'terminal',
                  child: ListTile(
                      leading: Icon(Icons.terminal),
                      title: Text('终端'),
                      contentPadding: EdgeInsets.zero)),
            ],
          ),
        ],
      ),
      body: Column(children: [
        Expanded(child: _body(state)),
        if (state.failedMessage != null) _failedBanner(),
        _composer(state),
      ]),
    );
  }

  Widget _body(ChatState state) {
    if (state.status == ChatStatus.loading) {
      return const Center(child: CircularProgressIndicator());
    }
    if (state.status == ChatStatus.error) {
      return Center(child: Text('加载失败: ${state.error}'));
    }
    final streaming = state.status == ChatStatus.streaming;
    return ListView(
      controller: _scroll,
      padding: const EdgeInsets.all(14),
      children: [
        for (final t in state.turns) ...[
          if (t.userImages.isNotEmpty) _sentImages(t.userImages),
          if (t.userText != null && t.userText!.isNotEmpty)
            _userBubble(t.userText!),
          TurnBlocks(t.blocks),
          const SizedBox(height: 18),
        ],
        if (streaming || state.live.isNotEmpty) ...[
          if (state.liveUserImages.isNotEmpty)
            _sentImages(state.liveUserImages),
          if (state.liveUser.isNotEmpty) _userBubble(state.liveUser),
          TurnBlocks(state.live),
          if (streaming) _typing(),
        ],
      ],
    );
  }

  Widget _typing() => Padding(
        padding: const EdgeInsets.only(top: 6),
        child: Row(children: const [
          SizedBox(
              width: 14,
              height: 14,
              child: CircularProgressIndicator(
                  strokeWidth: 2, color: AppTheme.teal)),
          SizedBox(width: 8),
          Text('正在生成…',
              style: TextStyle(color: AppTheme.muted, fontSize: 13)),
        ]),
      );

  Widget _userBubble(String text) => Align(
        alignment: Alignment.centerRight,
        child: Container(
          margin: const EdgeInsets.symmetric(vertical: 6),
          constraints: BoxConstraints(
              maxWidth: MediaQuery.of(context).size.width * 0.78),
          padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
          decoration: const BoxDecoration(
            color: AppTheme.teal,
            borderRadius: BorderRadius.only(
              topLeft: Radius.circular(16),
              topRight: Radius.circular(16),
              bottomLeft: Radius.circular(16),
              bottomRight: Radius.circular(4),
            ),
          ),
          child: Text(text,
              style: const TextStyle(
                  color: Colors.white, fontSize: 15, height: 1.4)),
        ),
      );

  // 已发图:右对齐缩略图(气泡上方)
  Widget _sentImages(List<String> paths) => Padding(
        padding: const EdgeInsets.only(bottom: 6),
        child: Align(
          alignment: Alignment.centerRight,
          child: Wrap(
            alignment: WrapAlignment.end,
            spacing: 6,
            runSpacing: 6,
            children: [for (final p in paths) _SentThumb(p)],
          ),
        ),
      );

  Widget _failedBanner() => Container(
        color: AppTheme.dangerSoft,
        padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 8),
        child: Row(children: [
          const Icon(Icons.error_outline, size: 18, color: AppTheme.danger),
          const SizedBox(width: 8),
          const Expanded(
              child: Text('发送失败', style: TextStyle(color: AppTheme.danger))),
          TextButton(
            onPressed: () => ref
                .read(chatControllerProvider(widget.sessionId).notifier)
                .retry(),
            child: const Text('重试'),
          ),
        ]),
      );

  Widget _composer(ChatState state) {
    final busy = state.status == ChatStatus.streaming || _uploading;
    return Container(
      decoration: const BoxDecoration(
        color: AppTheme.surface,
        border: Border(top: BorderSide(color: AppTheme.border)),
      ),
      child: SafeArea(
        top: false,
        child: Column(mainAxisSize: MainAxisSize.min, children: [
          if (_pending.isNotEmpty) _previewRow(),
          Padding(
            padding: const EdgeInsets.all(8),
            child: Row(crossAxisAlignment: CrossAxisAlignment.end, children: [
              IconButton(
                onPressed: busy ? null : _pickImages,
                icon: const Icon(Icons.add_photo_alternate_outlined),
                color: AppTheme.muted,
                tooltip: '添加图片',
              ),
              Expanded(
                child: TextField(
                  controller: _input,
                  minLines: 1,
                  maxLines: 5,
                  decoration: const InputDecoration(
                    hintText: '说点什么…',
                    contentPadding:
                        EdgeInsets.symmetric(horizontal: 14, vertical: 10),
                  ),
                ),
              ),
              const SizedBox(width: 8),
              _sendBtn(busy),
            ]),
          ),
        ]),
      ),
    );
  }

  Widget _sendBtn(bool busy) => Material(
        color: busy ? AppTheme.faint : AppTheme.teal,
        borderRadius: BorderRadius.circular(12),
        child: InkWell(
          borderRadius: BorderRadius.circular(12),
          onTap: busy ? null : _send,
          child: Padding(
            padding: const EdgeInsets.all(11),
            child: _uploading
                ? const SizedBox(
                    width: 20,
                    height: 20,
                    child: CircularProgressIndicator(
                        strokeWidth: 2, color: Colors.white))
                : const Icon(Icons.arrow_upward, color: Colors.white, size: 20),
          ),
        ),
      );

  Widget _previewRow() => Container(
        height: 80,
        alignment: Alignment.centerLeft,
        padding: const EdgeInsets.only(top: 8),
        child: ListView.separated(
          scrollDirection: Axis.horizontal,
          padding: const EdgeInsets.symmetric(horizontal: 8),
          itemCount: _pending.length,
          separatorBuilder: (_, _) => const SizedBox(width: 8),
          itemBuilder: (_, i) => Stack(children: [
            ClipRRect(
              borderRadius: BorderRadius.circular(10),
              child: Image.file(File(_pending[i].path),
                  width: 64, height: 64, fit: BoxFit.cover),
            ),
            Positioned(
              right: 2,
              top: 2,
              child: GestureDetector(
                onTap: () => setState(() => _pending.removeAt(i)),
                child: Container(
                  decoration: const BoxDecoration(
                      color: Colors.black54, shape: BoxShape.circle),
                  padding: const EdgeInsets.all(2),
                  child: const Icon(Icons.close, size: 14, color: Colors.white),
                ),
              ),
            ),
          ]),
        ),
      );
}

/// 已发图缩略图:带 token 取字节后 Image.memory(sentImageProvider 缓存)。
class _SentThumb extends ConsumerWidget {
  final String path;
  const _SentThumb(this.path);
  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final img = ref.watch(sentImageProvider(path));
    return ClipRRect(
      borderRadius: BorderRadius.circular(10),
      child: img.when(
        data: (bytes) =>
            Image.memory(bytes, width: 110, height: 110, fit: BoxFit.cover),
        loading: () => Container(
            width: 110,
            height: 110,
            color: AppTheme.borderSoft,
            child: const Center(
                child: SizedBox(
                    width: 18,
                    height: 18,
                    child: CircularProgressIndicator(strokeWidth: 2)))),
        error: (_, _) => Container(
            width: 110,
            height: 110,
            color: AppTheme.borderSoft,
            child: const Icon(Icons.broken_image_outlined,
                color: AppTheme.faint)),
      ),
    );
  }
}
