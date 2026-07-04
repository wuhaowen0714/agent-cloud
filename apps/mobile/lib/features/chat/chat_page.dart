import 'dart:async'; // unawaited
import 'dart:io';
import 'package:dio/dio.dart'; // DioException(区分 409/422 错误文案)
import 'package:flutter/material.dart';
import 'package:flutter/services.dart'; // Clipboard
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:file_selector/file_selector.dart';
import 'package:image_picker/image_picker.dart'; // 拍照直接问(系统相机,无需权限声明)
import '../../core/theme/app_theme.dart';
import '../../models/block.dart'; // TextBlock(提取「复制回答」文本)
import '../../models/skill.dart';
import '../agent/agent_repository.dart'; // agentRepoProvider / agentSkillsProvider(/ 技能启用)
import '../files/files_repository.dart';
import '../sessions/sessions_controller.dart';
import '../settings/platform_repository.dart';
import '../settings/skills_page.dart'; // skillsProvider(全部技能池)
import 'blocks.dart'; // Turn
import 'chat_controller.dart';
import 'chat_repository.dart'; // chatRepoProvider(手动压缩)
import 'file_ref.dart'; // atTokenAt / filterPaths(@ 文件引用)
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
  final List<String> _selectedSkills = []; // / 选中的技能(发送拼 [请使用技能:X] marker,发后清)
  AtToken? _atToken; // 当前 @ 文件引用词(null=无,光标离开 @ 词即消)
  int? _atDismissed; // Esc 关闭浮层的 @ 词 start;同一词内不再弹,词换位/消失解除
  bool _slashOpen = false; // / 技能浮层:输入框以 / 开头(单行)时打开

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    _input.addListener(_onInputChanged); // / 命令 + @ 文件引用:跟踪文本/光标派生浮层
    // 重进聊天页:controller(family,不随页面销毁)可能还压着排队消息且回合已在后台结束
    // → 补一次队列续发触发(idle+非空才动作,幂等)。
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (mounted) {
        ref.read(chatControllerProvider(widget.sessionId).notifier).kickQueue();
      }
    });
    if (widget.prefill != null && widget.prefill!.isNotEmpty) {
      // fork 出来的新会话:把被分叉的提问放回输入框。剥掉附件 marker 只回填正文(否则输入框
      // 会出现内部提示 + 裸路径、重发会再拼 marker);技能回填成 chip(对齐 web,技能已启用过)。
      final parsed = parseUserMessage(widget.prefill!);
      _input.text = parsed.body;
      _selectedSkills.addAll(parsed.skills);
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

  /// 附件入口:拍照直接问(对齐豆包拍题场景)或选相册/文件。
  Future<void> _pickAttachment() async {
    final choice = await showModalBottomSheet<String>(
      context: context,
      backgroundColor: Colors.white,
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.vertical(top: Radius.circular(20)),
      ),
      builder: (c) => SafeArea(
        child: Column(mainAxisSize: MainAxisSize.min, children: [
          const SizedBox(height: 8),
          ListTile(
            leading: const Icon(Icons.photo_camera_outlined, color: AppTheme.teal),
            title: const Text('拍照', style: TextStyle(fontSize: 15)),
            onTap: () => Navigator.pop(c, 'camera'),
          ),
          ListTile(
            leading: const Icon(Icons.attach_file, color: AppTheme.teal),
            title: const Text('相册 / 文件', style: TextStyle(fontSize: 15)),
            onTap: () => Navigator.pop(c, 'files'),
          ),
          const SizedBox(height: 4),
        ]),
      ),
    );
    if (choice == 'camera') {
      await _takePhoto();
    } else if (choice == 'files') {
      await _pickFiles();
    }
  }

  Future<void> _takePhoto() async {
    try {
      // 系统相机 Intent(image_picker):无需 CAMERA 权限声明;取消返回 null。
      final shot = await ImagePicker().pickImage(source: ImageSource.camera);
      if (shot != null && mounted) setState(() => _pending.add(shot));
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context)
            .showSnackBar(SnackBar(content: Text('拍照失败: $e')));
      }
    }
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

  // / 命令 + @ 文件引用:文本/光标变化时派生浮层状态(浮层渲染时才拉数据,这里不发请求)。
  void _onInputChanged() {
    final text = _input.text;
    final sel = _input.selection;
    final caret = sel.isValid ? sel.baseOffset : text.length;
    // / 技能:输入框是「/ + 单个词」——无第二个 / 与空白,排除路径 /usr/bin、正则 /re/、多词
    // 输入。[^/\s] 允许中文,故可 /文档 搜中文技能名(比 web 的 \w 更适配中文技能场景)。
    final slash = RegExp(r'^/[^/\s]*$').hasMatch(text);
    var at = atTokenAt(text, caret);
    // 豁免:同一 @ 词内 Esc 过则不弹;光标离开该词(token 为空或换了 start)即解除豁免。
    if (_atDismissed != null && (at == null || at.start != _atDismissed)) {
      _atDismissed = null;
    }
    if (at != null && _atDismissed == at.start) at = null;
    if (slash != _slashOpen || at != _atToken) {
      setState(() {
        _slashOpen = slash;
        _atToken = at;
      });
    }
  }

  /// / 选中技能:先启用到当前 agent(assemble 只注入 enabled_skills——不启用 agent 看不到技能
  /// 定义,marker 会让它调一个不认识的技能),再加成 chip;发送时拼 [请使用技能:X]。清 / 命令文本。
  Future<void> _pickSkill(Skill s) async {
    final aid = _agentId();
    if (aid == null) {
      _toast('会话信息未加载,请返回列表再进');
      return;
    }
    try {
      final enabled = await ref.read(agentSkillsProvider(aid).future);
      if (!enabled.any((e) => e.id == s.id)) {
        await ref
            .read(agentRepoProvider)
            .setAgentSkills(aid, [...enabled.map((e) => e.id), s.id]);
        ref.invalidate(agentSkillsProvider(aid));
      }
    } catch (e) {
      _toast('启用技能失败:$e');
      return;
    }
    if (!mounted) return;
    setState(() {
      if (!_selectedSkills.contains(s.name)) _selectedSkills.add(s.name);
      _slashOpen = false;
    });
    _input.clear(); // 清掉 / 命令文本(对齐 web 选技能后清空输入)
  }

  /// @ 选中文件:把 [start, caret) 替换成「@路径 」,光标落到尾空格后(焦点保持)。
  void _pickFile(String path) {
    final at = _atToken;
    if (at == null) return;
    final text = _input.text;
    final caret = _input.selection.baseOffset;
    final end = (caret >= at.start && caret <= text.length) ? caret : text.length;
    final insert = '@$path ';
    final next = text.substring(0, at.start) + insert + text.substring(end);
    _input.value = TextEditingValue(
      text: next,
      selection: TextSelection.collapsed(offset: at.start + insert.length),
    );
    setState(() => _atToken = null);
  }

  Future<void> _send() async {
    final text = _input.text.trim();
    if (text.isEmpty && _pending.isEmpty) {
      // 仅选了技能、没正文也没附件:技能只说明"用哪个工具",本身不含需求(对齐 web)。
      if (_selectedSkills.isNotEmpty) _toast('补充你的需求后再发送');
      return;
    }
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
    // 正文(含 @路径原样)+ 选中技能(拼 [请使用技能:X] marker)+ 附件,三段组装(对标 web)。
    final sent = composeMessage(text, _selectedSkills, paths);
    // 有图但当前模型不支持图片 → 自动切到平台 vision 模型(对标 web;后端从 session 读 model,
    // 故先 await patchModel 落库再发)。无 vision 模型可切则提示、保留待发。
    if (sent.images.isNotEmpty && !_modelSupportsVision()) {
      final target = _pickVisionModel();
      if (target == null) {
        if (mounted) {
          ScaffoldMessenger.of(context).showSnackBar(
              const SnackBar(content: Text('当前没有支持图片的模型可用')));
        }
        return;
      }
      try {
        await ref
            .read(sessionsControllerProvider.notifier)
            .patchModel(widget.sessionId, target);
        if (mounted) {
          ScaffoldMessenger.of(context).showSnackBar(
              SnackBar(content: Text('已自动切换到 $target(支持图片)')));
        }
      } catch (_) {
        if (mounted) {
          ScaffoldMessenger.of(context).showSnackBar(const SnackBar(
              content: Text('自动切换模型失败,请手动切到支持图片的模型')));
        }
        return;
      }
    }
    _input.clear();
    setState(() {
      _pending.clear();
      _selectedSkills.clear();
      _atToken = null;
      _atDismissed = null; // 防 @ 豁免跨消息泄漏(对齐 web 审查 M1)
    });
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

  // 选一个 vision 模型来自动切:平台 vision 列表第一个。无则 null。
  String? _pickVisionModel() {
    final pm = ref.read(platformModelsProvider).asData?.value;
    if (pm == null || pm.visionModels.isEmpty) return null;
    return pm.visionModels.first;
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
    if (v == 'compact') {
      _compact();
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

  /// 批准被拦的危险操作:发送含批准码的确认消息(生成中自动排队,回合结束发出;
  /// agent 收到后重试同一命令即被放行)。
  void _approve(String text) {
    ref.read(chatControllerProvider(widget.sessionId).notifier).send(text);
  }

  /// 手动压缩会话上下文(对齐 web /compact):把较早的历史折叠成摘要,给长对话腾上下文。
  Future<void> _compact() async {
    final chat = ref.read(chatControllerProvider(widget.sessionId));
    if (chat.status == ChatStatus.streaming) {
      _toast('回合进行中,结束后再压缩');
      return;
    }
    _toast('正在压缩上下文…');
    try {
      final compacted = await ref
          .read(chatRepoProvider)
          .compactSession(widget.sessionId);
      _toast(compacted ? '压缩完成' : '当前没有可压缩的内容');
    } catch (e) {
      _toast(_errMsg(e, '压缩失败,请重试'));
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
              PopupMenuItem(
                  value: 'compact',
                  child: ListTile(
                      leading: Icon(Icons.compress),
                      title: Text('压缩上下文'),
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
          _userSection(t.userText, t.userImages),
          TurnBlocks(t.blocks, onApprove: _approve),
          _turnActionBar(t, streaming,
              isLast: identical(t, state.turns.last)), // 豆包式常驻操作栏
          const SizedBox(height: 18),
        ],
        if (streaming || state.live.isNotEmpty) ...[
          _userSection(state.liveUser, state.liveUserImages),
          TurnBlocks(state.live, onApprove: _approve),
          if (streaming) _typing(state.compacting),
        ],
      ],
    );
  }

  Widget _typing(bool compacting) => Padding(
        padding: const EdgeInsets.only(top: 6),
        child: Row(children: [
          const SizedBox(
              width: 14,
              height: 14,
              child: CircularProgressIndicator(
                  strokeWidth: 2, color: AppTheme.teal)),
          const SizedBox(width: 8),
          Text(compacting ? '正在压缩上下文…' : '正在生成…',
              style: const TextStyle(color: AppTheme.muted, fontSize: 13)),
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

  // 用户回合区:图片缩略图(上)+ 非图片附件 chip + 正文气泡。发送时拼进 content 的 marker/
  // 路径由 parseUserMessage 摘掉,气泡只显示用户真正打的字(图片走缩略图、文件走 chip)。
  Widget _userSection(String? rawText, List<String> userImages) {
    final parsed =
        (rawText == null || rawText.isEmpty) ? null : parseUserMessage(rawText);
    final body = parsed?.body ?? '';
    final files = (parsed?.attachments ?? const <String>[])
        .where((p) => !isImagePath(p))
        .toList();
    final skills = parsed?.skills ?? const <String>[];
    return Column(
      mainAxisSize: MainAxisSize.min,
      crossAxisAlignment: CrossAxisAlignment.end,
      children: [
        if (userImages.isNotEmpty) _sentImages(userImages),
        if (files.isNotEmpty) _fileChips(files),
        if (skills.isNotEmpty) _skillChips(skills), // 只读:这条消息选用的技能
        if (body.isNotEmpty) _userBubble(body, onLongPress: () => _copy(body)),
      ],
    );
  }

  // 非图片附件:右对齐的文件名 chip(图片走缩略图,这里放文档/压缩包等)。
  Widget _fileChips(List<String> paths) => Padding(
        padding: const EdgeInsets.only(bottom: 6),
        child: Align(
          alignment: Alignment.centerRight,
          child: Wrap(
            alignment: WrapAlignment.end,
            spacing: 6,
            runSpacing: 6,
            children: [
              for (final p in paths)
                Container(
                  padding:
                      const EdgeInsets.symmetric(horizontal: 10, vertical: 7),
                  decoration: BoxDecoration(
                    color: const Color(0xFFF1F3F4),
                    borderRadius: BorderRadius.circular(9),
                  ),
                  child: Row(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      const Icon(Icons.insert_drive_file_outlined,
                          size: 15, color: AppTheme.teal),
                      const SizedBox(width: 6),
                      ConstrainedBox(
                        constraints: BoxConstraints(
                            maxWidth:
                                MediaQuery.of(context).size.width * 0.5),
                        child: Text(_fileName(p),
                            overflow: TextOverflow.ellipsis,
                            style: const TextStyle(
                                color: Colors.black87, fontSize: 13)),
                      ),
                    ],
                  ),
                ),
            ],
          ),
        ),
      );

  // 上传文件展示名:去路径前缀,再去后端加的 <毫秒时间戳(13+位)>_<序号>_ 前缀还原原名。
  // 时间戳锚 13+ 位,避免误剥用户原名里的 2024_01_ 这类短数字前缀。
  String _fileName(String path) =>
      path.split('/').last.replaceFirst(RegExp(r'^\d{13,}_\d+_'), '');

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
  Widget _turnActionBar(Turn t, bool streaming, {bool isLast = false}) {
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
          // 重新生成(对齐豆包):删掉本回合回答、用原文原图立即重发。仅最后一个回合
          // 提供——中间回合重发会连带删掉其后所有历史,那是「回到这里」的职责。
          if (isLast)
            _actionChip(Icons.refresh, '重新生成',
                streaming ? null : () => _regenerate(t)),
        ],
      ),
    );
  }

  /// 重新生成 = 回滚该回合 + 用原始内容(含技能/附件 marker 与图片)自动重发。
  Future<void> _regenerate(Turn t) async {
    if (_actionBusy) return;
    _actionBusy = true;
    try {
      final ctrl = ref.read(chatControllerProvider(widget.sessionId).notifier);
      final text = await ctrl.rollback(t.id); // 原始 content(含 marker),回填语义同 rewind
      unawaited(
          ref.read(sessionsControllerProvider.notifier).refresh()); // 列表时间戳
      if (!mounted) return;
      unawaited(ctrl.send(text, images: t.userImages)); // 原图路径仍在工作区,直接重发
    } catch (e) {
      _toast(_errMsg(e, '重新生成失败,请重试'));
    } finally {
      _actionBusy = false;
    }
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
      final parsed = parseUserMessage(text);
      _input.text = parsed.body; // 同 prefill:回填正文,不带附件 marker
      setState(() {
        _selectedSkills
          ..clear()
          ..addAll(parsed.skills); // 技能回填成 chip(对齐 web)
      });
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
    // 生成中不再锁输入:发送=排队(对标 Claude Code),仅上传附件在途时短暂禁用。
    final streaming = state.status == ChatStatus.streaming;
    return Container(
      decoration: const BoxDecoration(
        color: AppTheme.surface,
        border: Border(top: BorderSide(color: AppTheme.border)),
      ),
      child: SafeArea(
        top: false,
        child: Column(mainAxisSize: MainAxisSize.min, children: [
          _overlayPanel(), // / 技能 或 @ 文件 浮层(无则不占位)
          if (state.queued.isNotEmpty) _queuedRow(state.queued),
          if (_selectedSkills.isNotEmpty)
            Padding(
              padding: const EdgeInsets.fromLTRB(8, 6, 8, 0),
              child: _skillChips(_selectedSkills, onDelete: _removeSkill),
            ),
          if (_pending.isNotEmpty) _previewRow(),
          Padding(
            padding: const EdgeInsets.all(8),
            child: Row(crossAxisAlignment: CrossAxisAlignment.end, children: [
              IconButton(
                onPressed: _uploading ? null : _pickAttachment,
                icon: const Icon(Icons.attach_file),
                color: AppTheme.muted,
                tooltip: '添加文件',
              ),
              Expanded(
                child: TextField(
                  controller: _input,
                  minLines: 1,
                  maxLines: 5,
                  decoration: InputDecoration(
                    hintText: streaming
                        ? '继续输入,发送将加入队列…'
                        : '说点什么(/ 技能 · @ 文件)…',
                    contentPadding: const EdgeInsets.symmetric(
                        horizontal: 14, vertical: 10),
                  ),
                ),
              ),
              const SizedBox(width: 8),
              if (streaming) ...[_stopBtn(), const SizedBox(width: 8)],
              _sendBtn(streaming),
            ]),
          ),
        ]),
      ),
    );
  }

  /// 排队消息行:生成中排队的消息(队首下一个发出),可单条删除。
  Widget _queuedRow(List<QueuedMessage> queued) => Padding(
        padding: const EdgeInsets.fromLTRB(8, 6, 8, 0),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            for (var i = 0; i < queued.length; i++)
              Container(
                margin: const EdgeInsets.only(bottom: 4),
                padding: const EdgeInsets.fromLTRB(10, 6, 6, 6),
                decoration: BoxDecoration(
                  color: const Color(0xFFF1F3F4),
                  borderRadius: BorderRadius.circular(9),
                ),
                child: Row(children: [
                  const Icon(Icons.schedule, size: 14, color: AppTheme.muted),
                  const SizedBox(width: 6),
                  Expanded(
                    child: Builder(builder: (_) {
                      final body = parseUserMessage(queued[i].content).body;
                      return Text(
                        body.isEmpty ? '(附件)' : body,
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                        style: const TextStyle(
                            fontSize: 12.5, color: Colors.black54),
                      );
                    }),
                  ),
                  InkWell(
                    onTap: () => ref
                        .read(chatControllerProvider(widget.sessionId).notifier)
                        .removeQueued(i),
                    child: const Padding(
                      padding: EdgeInsets.all(3),
                      child:
                          Icon(Icons.close, size: 14, color: AppTheme.muted),
                    ),
                  ),
                ]),
              ),
          ],
        ),
      );

  /// 停止按钮:取消当前回合(排队消息一并清除)。
  Widget _stopBtn() => Material(
        color: const Color(0xFFFEE2E2), // red-100
        borderRadius: BorderRadius.circular(12),
        child: InkWell(
          borderRadius: BorderRadius.circular(12),
          onTap: () => ref
              .read(chatControllerProvider(widget.sessionId).notifier)
              .stopTurn(),
          child: Padding(
            padding: const EdgeInsets.all(11),
            child: Icon(Icons.stop_rounded,
                color: Colors.red.shade600, size: 20),
          ),
        ),
      );

  void _removeSkill(String s) => setState(() => _selectedSkills.remove(s));

  /// 技能 chip:teal-50 底 + teal 边/字 + 🧩。onDelete 非空 = 发送区可删;空 = 气泡只读。
  Widget _skillChips(List<String> skills, {void Function(String)? onDelete}) =>
      Align(
        alignment: Alignment.centerRight,
        child: Wrap(
          alignment: WrapAlignment.end,
          spacing: 6,
          runSpacing: 6,
          children: [
            for (final s in skills)
              Container(
                padding: EdgeInsets.fromLTRB(9, 5, onDelete != null ? 5 : 9, 5),
                decoration: BoxDecoration(
                  color: AppTheme.tealSoft,
                  borderRadius: BorderRadius.circular(9),
                  border: Border.all(color: AppTheme.teal.withValues(alpha: 0.4)),
                ),
                child: Row(mainAxisSize: MainAxisSize.min, children: [
                  const Icon(Icons.extension, size: 13, color: AppTheme.tealDark),
                  const SizedBox(width: 4),
                  Text(s,
                      style: const TextStyle(
                          fontSize: 12.5, color: AppTheme.tealDark)),
                  if (onDelete != null) ...[
                    const SizedBox(width: 3),
                    InkWell(
                      onTap: () => onDelete(s),
                      child: const Icon(Icons.close,
                          size: 14, color: AppTheme.tealDark),
                    ),
                  ],
                ]),
              ),
          ],
        ),
      );

  // / 技能 或 @ 文件 浮层(输入框上方)。@ 词活跃时压过 / 面板(对齐 web)。
  Widget _overlayPanel() {
    if (_atToken != null) return _fileRefPanel(_atToken!);
    if (_slashOpen) return _skillPanel();
    return const SizedBox.shrink();
  }

  Widget _skillPanel() {
    final query =
        _input.text.startsWith('/') ? _input.text.substring(1).toLowerCase() : '';
    void close() => setState(() => _slashOpen = false); // 关浮层(再输入会按 / 规则重判)
    return ref.watch(skillsProvider).when(
          loading: () => _panelShell([_panelHint('加载技能…')], onClose: close),
          error: (_, _) => _panelShell([_panelHint('技能加载失败')], onClose: close),
          data: (all) {
            final matched = all
                .where((s) => s.name.toLowerCase().contains(query))
                .take(20)
                .toList();
            if (matched.isEmpty) {
              return _panelShell([_panelHint('无匹配技能')], onClose: close);
            }
            return _panelShell([
              for (final s in matched)
                _panelItem(
                  icon: Icons.extension,
                  title: s.name,
                  subtitle: s.description,
                  onTap: () => _pickSkill(s),
                ),
            ], onClose: close);
          },
        );
  }

  Widget _fileRefPanel(AtToken at) {
    // 关浮层:清 _atToken 立即收起 + 记 _atDismissed,让同一 @ 词内继续打字也不再弹。
    void close() => setState(() {
          _atToken = null;
          _atDismissed = at.start;
        });
    return ref.watch(fileIndexProvider).when(
          loading: () => _panelShell([_panelHint('索引文件…')], onClose: close),
          error: (_, _) => _panelShell([_panelHint('文件索引失败')], onClose: close),
          data: (index) {
            final matched = filterPaths(index, at.query);
            if (matched.isEmpty) {
              return _panelShell([_panelHint('无匹配文件')], onClose: close);
            }
            return _panelShell([
              for (final p in matched)
                _panelItem(
                  icon: Icons.insert_drive_file_outlined,
                  title: _fileName(p),
                  subtitle: p,
                  onTap: () => _pickFile(p),
                ),
            ], onClose: close);
          },
        );
  }

  Widget _panelShell(List<Widget> children, {VoidCallback? onClose}) =>
      Container(
        constraints: const BoxConstraints(maxHeight: 240),
        margin: const EdgeInsets.fromLTRB(8, 8, 8, 0),
        decoration: BoxDecoration(
          color: AppTheme.surface,
          borderRadius: BorderRadius.circular(12),
          border: Border.all(color: AppTheme.border),
        ),
        child: Column(mainAxisSize: MainAxisSize.min, children: [
          if (onClose != null)
            Align(
              alignment: Alignment.centerRight,
              child: InkWell(
                onTap: onClose,
                borderRadius: BorderRadius.circular(8),
                child: const Padding(
                  padding: EdgeInsets.all(6),
                  child: Icon(Icons.close, size: 16, color: AppTheme.muted),
                ),
              ),
            ),
          Flexible(
            child: ListView(
              shrinkWrap: true,
              padding: const EdgeInsets.only(bottom: 4),
              children: children,
            ),
          ),
        ]),
      );

  Widget _panelItem({
    required IconData icon,
    required String title,
    required String subtitle,
    required VoidCallback onTap,
  }) =>
      InkWell(
        onTap: onTap,
        child: Padding(
          padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
          child: Row(children: [
            Icon(icon, size: 16, color: AppTheme.teal),
            const SizedBox(width: 10),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(title,
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: const TextStyle(fontSize: 14, color: AppTheme.ink)),
                  if (subtitle.isNotEmpty)
                    Text(subtitle,
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                        style: const TextStyle(
                            fontSize: 11.5, color: AppTheme.muted)),
                ],
              ),
            ),
          ]),
        ),
      );

  Widget _panelHint(String text) => Padding(
        padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
        child: Text(text,
            style: const TextStyle(fontSize: 13, color: AppTheme.muted)),
      );

  Widget _sendBtn(bool streaming) => Material(
        color: _uploading ? AppTheme.faint : AppTheme.teal,
        borderRadius: BorderRadius.circular(12),
        child: InkWell(
          borderRadius: BorderRadius.circular(12),
          onTap: _uploading ? null : _send, // 生成中照发:controller 守卫转排队
          child: Padding(
            padding: const EdgeInsets.all(11),
            child: _uploading
                ? const SizedBox(
                    width: 20,
                    height: 20,
                    child: CircularProgressIndicator(
                        strokeWidth: 2, color: Colors.white))
                : Icon(streaming ? Icons.playlist_add : Icons.arrow_upward,
                    color: Colors.white, size: 20),
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
