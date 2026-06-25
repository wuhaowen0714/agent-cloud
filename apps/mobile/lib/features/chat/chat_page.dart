import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'chat_controller.dart';
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

  @override
  void dispose() {
    _input.dispose();
    _scroll.dispose();
    super.dispose();
  }

  void _send() {
    final text = _input.text.trim();
    if (text.isEmpty) return;
    _input.clear();
    ref.read(chatControllerProvider(widget.sessionId).notifier).send(text);
  }

  @override
  Widget build(BuildContext context) {
    final state = ref.watch(chatControllerProvider(widget.sessionId));
    return Scaffold(
      appBar: AppBar(title: const Text('对话')),
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
    final busy = state.status == ChatStatus.streaming;
    return SafeArea(
      child: Padding(
        padding: const EdgeInsets.all(8),
        child: Row(children: [
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
              onPressed: busy ? null : _send, icon: const Icon(Icons.send)),
        ]),
      ),
    );
  }
}
