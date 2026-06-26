import 'dart:io';
import 'package:dio/dio.dart'; // DioException(区分 409/422 错误文案)
import 'package:flutter/material.dart';
import 'package:flutter/services.dart'; // Clipboard
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:file_selector/file_selector.dart';
import '../../core/theme/app_theme.dart';
import '../../models/block.dart'; // TextBlock(提取「复制回答」文本)
import '../files/files_repository.dart';
import '../sessions/sessions_controller.dart';
import '../settings/platform_repository.dart';
import 'blocks.dart'; // Turn
import 'chat_controller.dart';
import 'model_picker.dart';
import 'turn_blocks.dart';
import 'upload_compose.dart';

class ChatPage extends ConsumerStatefulWidget {
  final String sessionId;
  final String? prefill; // fork 跳转后回填到输入框的提问文本
  const ChatPage(this.sessionId, {super.key, this.prefill});
  @override
  ConsumerState<ChatPage> createState() => _ChatPageState();
}

class _ChatPageState extends ConsumerState<ChatPage>
    with WidgetsBindingObserver {
  final _input = TextEditingController();
  final _scroll = ScrollController();
  final List<XFile> _pending = []; // 待发附件(图片 + 任意文件)
  bool _uploading = false;
  bool _actionBusy = false; // fork/rewind 在途互斥:防双触发(第二次会撞已删消息 409/422)

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    if (widget.prefill != null && widget.prefill!.isNotEmpty) {
      _input.text = widget.prefill!; // fork 出来的新会话:把被分叉的提问放回输入框
    }
  }

  // 客户端动作工具(set_alarm/add_calendar_event)会拉起系统闹钟/日历 App,把本 app 切到后台
  // → SSE 流被系统中断;回前台时若回合仍"生成中",主动续看(resume)被中断的流,否则会永久卡
  // 在"正在生成"(回合其实已在服务端跑完)。
  @override
  void didChangeAppLifecycleState(AppLifecycleState lifecycle) {
    if (lifecycle == AppLifecycleState.resumed && mounted) {
      final chat = ref.read(chatControllerProvider(widget.sessionId));
      if (chat.status == ChatStatus.streaming) {
        ref
            .read(chatControllerProvider(widget.sessionId).notifier)
            .retryResume();
      }
    }
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    _input.dispose();
    _scroll.dispose();
    super.dispose();
  }

  Future<void> _pickFiles() async {
    try {
      final files = await openFiles();
      if (files.isNotEmpty && mounted) setState(() => _pending.addAll(files));
    } catch (e) {
      // 系统选择器偶发 SecurityException / 路径解析失败 → 提示而非静默失败。
      if (mounted) {
        ScaffoldMessenger.of(context)
            .showSnackBar(SnackBar(content: Text('选择文件失败: $e')));
      }
    }
  }

  Future<void> _send() async {
    final text = _input.text.trim();
    if (text.isEmpty && _pending.isEmpty) return;
    var paths = <String>[];
    if (_pending.isNotEmpty) {
      setState(() => _uploading = true);
      try {
        paths = await ref.read(filesRepoProvider).uploadFiles(_pending);
      } catch (e) {
        if (!mounted) return;
        setState(() => _uploading = false);
        ScaffoldMessenger.of(context)
            .showSnackBar(SnackBar(content: Text('文件上传失败: $e')));
        return; // 保留待发文件,可重试
      }
      if (!mounted) return;
      setState(() => _uploading = false);
    }
    // 图片走多模态 vision,其余文件把路径作为文本引用拼进正文(对标 web)。
    final sent = composeUpload(text, paths);
    // vision 门控:有图但当前会话模型不支持图片 → 提示切模型,保留待发(对标 web)。
    if (sent.images.isNotEmpty && !_modelSupportsVision()) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(const SnackBar(
            content: Text('当前模型不支持图片,请点右上角切到带「图片」标记的模型')));
      }
      return;
    }
    _input.clear();
    setState(() => _pending.clear());
    ref
        .read(chatControllerProvider(widget.sessionId).notifier)
        .send(sent.content, images: sent.images);
  }

  // 当前会话模型是否支持图片输入。清单未加载/模型未知时保守不拦(返回 true,交后端)。
  bool _modelSupportsVision() {
    final pm = ref.read(platformModelsProvider).asData?.value;
    if (pm == null) return true;
    final sessions = ref.read(sessionsControllerProvider).asData?.value ?? [];
    final m = sessions.where((s) => s.id == widget.sessionId);
    final model = m.isEmpty ? null : m.first.model;
    if (model == null) return true;
    return pm.visionModels.contains(model);
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
            _userBubble(t.userText!, onLongPress: () => _copy(t.userText!)),
          TurnBlocks(t.blocks),
          _turnActionBar(t, streaming), // 豆包式:回答下方常驻操作栏(复制/分叉/回到这里)
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

  Widget _userBubble(String text, {VoidCallback? onLongPress}) => Align(
        alignment: Alignment.centerRight,
        child: GestureDetector(
          onLongPress: onLongPress,
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
        ),
      );

  // ── 消息级操作:复制 / 分叉 / 回到这里(对标 web)──

  /// 该回合 assistant 的可见正文(拼接所有 TextBlock;思考/工具输出不计入「复制回答」)。
  String _assistantText(Turn t) => t.blocks
      .whereType<TextBlock>()
      .map((b) => b.text.trim())
      .where((s) => s.isNotEmpty)
      .join('\n\n');

  /// 回答下方常驻操作栏(仿豆包):复制回答 / 从这里分叉 / 回到这里。一行轻量按钮,
  /// 直接可见可点,不再走长按弹窗。回滚销毁性、与回合同锁 → 本会话生成中禁用(后端也会 409);
  /// 复制、分叉只读,始终可用。回答为空(纯工具回合)时不显示「复制」。
  Widget _turnActionBar(Turn t, bool streaming) {
    final answer = _assistantText(t);
    return Padding(
      padding: const EdgeInsets.only(top: 8, left: 2),
      child: Wrap(
        spacing: 8,
        runSpacing: 6,
        children: [
          if (answer.isNotEmpty)
            _actionChip(Icons.content_copy_outlined, '复制', () => _copy(answer)),
          _actionChip(Icons.call_split, '分叉', () => _fork(t.id)),
          _actionChip(
              Icons.history, '回到这里', streaming ? null : () => _rewind(t)),
        ],
      ),
    );
  }

  /// 单个操作按钮(纯图标 + 浅底方块,仿豆包):长按弹 tooltip 文字辅助识别,兼顾可发现性。
  /// onTap 为 null = 禁用(置灰)。
  Widget _actionChip(IconData icon, String tooltip, VoidCallback? onTap) {
    final enabled = onTap != null;
    return Tooltip(
      message: tooltip,
      child: Material(
        color: Colors.transparent,
        child: InkWell(
          onTap: onTap,
          borderRadius: BorderRadius.circular(9),
          child: Container(
            padding: const EdgeInsets.all(8),
            decoration: BoxDecoration(
              color: const Color(0xFFF1F3F4),
              borderRadius: BorderRadius.circular(9),
            ),
            child: Icon(icon,
                size: 18, color: enabled ? AppTheme.teal : Colors.black26),
          ),
        ),
      ),
    );
  }

  void _copy(String text) {
    Clipboard.setData(ClipboardData(text: text));
    _toast('已复制');
  }

  void _toast(String msg) {
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(content: Text(msg), duration: const Duration(seconds: 1)),
    );
  }

  /// 把 fork/rollback 的异常转成短提示。409=会话忙(rollback 与回合同锁的高频预期路径),
  /// 422=消息已被删/不可操作(多为重复触发),其余给静态兜底——别把 DioException 原串塞进 toast。
  String _errMsg(Object e, String fallback) {
    if (e is DioException) {
      final code = e.response?.statusCode;
      if (code == 409) return '会话正忙,请稍候再试';
      if (code == 422) return '该消息已不可操作';
    }
    return fallback;
  }

  /// 从某条提问分叉新会话:复制其之前的历史到新会话,跳转过去并把该提问回填输入框。
  Future<void> _fork(String messageId) async {
    if (_actionBusy) return; // 防双触发:在途时第二次会撞已建/已删,弹假错误
    _actionBusy = true;
    try {
      final r = await ref
          .read(chatControllerProvider(widget.sessionId).notifier)
          .fork(messageId);
      await ref.read(sessionsControllerProvider.notifier).refresh();
      if (!mounted) return;
      context.push('/chat/${r.newSessionId}', extra: r.userText);
    } catch (e) {
      _toast(_errMsg(e, '分叉失败,请重试'));
    } finally {
      _actionBusy = false;
    }
  }

  /// 回到某条提问之前:确认后删它及其后的全部消息,把该提问放回输入框可重问。
  Future<void> _rewind(Turn t) async {
    if (_actionBusy) return;
    final ok = await showDialog<bool>(
      context: context,
      builder: (c) => AlertDialog(
        title: const Text('回到这里'),
        content: const Text('将删除这条提问及其之后的所有消息,提问内容会放回输入框。此操作不可撤销。'),
        actions: [
          TextButton(
              onPressed: () => Navigator.pop(c, false),
              child: const Text('取消')),
          TextButton(
            onPressed: () => Navigator.pop(c, true),
            child: Text('删除', style: TextStyle(color: Colors.red.shade600)),
          ),
        ],
      ),
    );
    if (ok != true) return;
    _actionBusy = true;
    try {
      final text = await ref
          .read(chatControllerProvider(widget.sessionId).notifier)
          .rollback(t.id);
      await ref.read(sessionsControllerProvider.notifier).refresh();
      if (!mounted) return;
      _input.text = text;
      _toast('已回到此处');
    } catch (e) {
      _toast(_errMsg(e, '回滚失败,请重试'));
    } finally {
      _actionBusy = false;
    }
  }

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
                onPressed: busy ? null : _pickFiles,
                icon: const Icon(Icons.attach_file),
                color: AppTheme.muted,
                tooltip: '添加文件',
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
            _pendingThumb(_pending[i]),
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

  // 待发预览:图片显缩略图,其它文件显图标 + 文件名。
  Widget _pendingThumb(XFile f) {
    if (isImagePath(f.name)) {
      return ClipRRect(
        borderRadius: BorderRadius.circular(10),
        child: Image.file(File(f.path),
            width: 64, height: 64, fit: BoxFit.cover),
      );
    }
    return Container(
      width: 64,
      height: 64,
      padding: const EdgeInsets.symmetric(horizontal: 3),
      decoration: BoxDecoration(
        color: AppTheme.bg,
        borderRadius: BorderRadius.circular(10),
        border: Border.all(color: AppTheme.border),
      ),
      child: Column(mainAxisAlignment: MainAxisAlignment.center, children: [
        const Icon(Icons.insert_drive_file_outlined,
            size: 22, color: AppTheme.muted),
        const SizedBox(height: 2),
        Text(f.name,
            maxLines: 1,
            overflow: TextOverflow.ellipsis,
            style: const TextStyle(fontSize: 9, color: AppTheme.muted)),
      ]),
    );
  }
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
