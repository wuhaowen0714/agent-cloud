import 'dart:io';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:image_picker/image_picker.dart';
import '../files/files_repository.dart';
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

  @override
  Widget build(BuildContext context) {
    final state = ref.watch(chatControllerProvider(widget.sessionId));
    return Scaffold(
      appBar: AppBar(
        title: const Text('对话'),
        actions: [
          IconButton(
            icon: const Icon(Icons.tune),
            tooltip: '切换模型',
            onPressed: () => showModelPicker(context, ref, widget.sessionId),
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
      padding: const EdgeInsets.all(12),
      children: [
        for (final t in state.turns) ...[
          if (t.userText != null && t.userText!.isNotEmpty)
            _userBubble(t.userText!),
          TurnBlocks(t.blocks),
          const SizedBox(height: 16),
        ],
        if (streaming || state.live.isNotEmpty) ...[
          if (state.liveUser.isNotEmpty) _userBubble(state.liveUser),
          TurnBlocks(state.live),
          if (streaming)
            const Padding(
                padding: EdgeInsets.all(8),
                child: Text('▍', style: TextStyle(color: Colors.teal))),
        ],
      ],
    );
  }

  Widget _userBubble(String text) => Align(
        alignment: Alignment.centerRight,
        child: Container(
          margin: const EdgeInsets.symmetric(vertical: 6),
          padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
          decoration: BoxDecoration(
              color: Colors.teal.shade50,
              borderRadius: BorderRadius.circular(12)),
          child: Text(text),
        ),
      );

  Widget _failedBanner() => Container(
        color: Colors.red.shade50,
        padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 4),
        child: Row(children: [
          const Expanded(
              child: Text('发送失败', style: TextStyle(color: Colors.red))),
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
    return SafeArea(
      child: Column(mainAxisSize: MainAxisSize.min, children: [
        if (_pending.isNotEmpty) _previewRow(),
        Padding(
          padding: const EdgeInsets.all(8),
          child: Row(children: [
            IconButton(
              onPressed: busy ? null : _pickImages,
              icon: const Icon(Icons.image_outlined),
              tooltip: '添加图片',
            ),
            Expanded(
              child: TextField(
                controller: _input,
                minLines: 1,
                maxLines: 4,
                decoration: const InputDecoration(
                    hintText: '说点什么…', border: OutlineInputBorder()),
              ),
            ),
            const SizedBox(width: 8),
            IconButton.filled(
              onPressed: busy ? null : _send,
              icon: _uploading
                  ? const SizedBox(
                      width: 18,
                      height: 18,
                      child: CircularProgressIndicator(strokeWidth: 2))
                  : const Icon(Icons.send),
            ),
          ]),
        ),
      ]),
    );
  }

  Widget _previewRow() => Container(
        height: 76,
        alignment: Alignment.centerLeft,
        child: ListView.separated(
          scrollDirection: Axis.horizontal,
          padding: const EdgeInsets.symmetric(horizontal: 8),
          itemCount: _pending.length,
          separatorBuilder: (_, _) => const SizedBox(width: 8),
          itemBuilder: (_, i) => Stack(children: [
            ClipRRect(
              borderRadius: BorderRadius.circular(8),
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
