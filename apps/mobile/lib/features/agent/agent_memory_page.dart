import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../../core/theme/app_theme.dart';
import 'agent_repository.dart';

/// agent 专属记忆(scope=agent):这个智能体跨会话记住的内容,可手动编辑/清除。
class AgentMemoryPage extends ConsumerStatefulWidget {
  final String agentId;
  const AgentMemoryPage(this.agentId, {super.key});
  @override
  ConsumerState<AgentMemoryPage> createState() => _AgentMemoryPageState();
}

class _AgentMemoryPageState extends ConsumerState<AgentMemoryPage> {
  final _ctrl = TextEditingController();
  bool _loading = true;
  bool _saving = false;
  bool _loadFailed = false;

  @override
  void initState() {
    super.initState();
    _load();
  }

  @override
  void dispose() {
    _ctrl.dispose();
    super.dispose();
  }

  Future<void> _load() async {
    try {
      _ctrl.text =
          await ref.read(agentRepoProvider).getAgentMemory(widget.agentId);
    } catch (_) {
      _loadFailed = true; // 加载失败别让用户在空框上保存、覆盖真实记忆
    }
    if (mounted) setState(() => _loading = false);
  }

  void _retry() {
    setState(() {
      _loading = true;
      _loadFailed = false;
    });
    _load();
  }

  Future<void> _save() async {
    setState(() => _saving = true);
    try {
      await ref
          .read(agentRepoProvider)
          .putAgentMemory(widget.agentId, _ctrl.text.trim());
      if (mounted) {
        ScaffoldMessenger.of(context)
            .showSnackBar(const SnackBar(content: Text('已保存')));
      }
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context)
            .showSnackBar(SnackBar(content: Text('保存失败: $e')));
      }
    }
    if (mounted) setState(() => _saving = false);
  }

  Future<void> _clear() async {
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('清除记忆'),
        content: const Text('确定清空这个智能体的记忆?此操作不可撤销。'),
        actions: [
          TextButton(
              onPressed: () => Navigator.pop(ctx, false),
              child: const Text('取消')),
          TextButton(
              onPressed: () => Navigator.pop(ctx, true),
              child: const Text('清除',
                  style: TextStyle(color: AppTheme.danger))),
        ],
      ),
    );
    if (ok != true) return;
    try {
      await ref.read(agentRepoProvider).clearAgentMemory(widget.agentId);
      _ctrl.clear();
      if (mounted) {
        setState(() {});
        ScaffoldMessenger.of(context)
            .showSnackBar(const SnackBar(content: Text('已清除')));
      }
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context)
            .showSnackBar(SnackBar(content: Text('清除失败: $e')));
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('记忆'),
        actions: [
          IconButton(
              onPressed: _loading ? null : _clear,
              icon: const Icon(Icons.delete_sweep_outlined),
              tooltip: '清除'),
        ],
      ),
      body: _loading
          ? const Center(child: CircularProgressIndicator())
          : _loadFailed
              ? Center(
                  child: Column(mainAxisSize: MainAxisSize.min, children: [
                    const Text('记忆加载失败',
                        style: TextStyle(color: AppTheme.muted)),
                    const SizedBox(height: 12),
                    OutlinedButton(
                        onPressed: _retry, child: const Text('重试')),
                  ]),
                )
              : Padding(
              padding: const EdgeInsets.all(16),
              child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    const Text('这个智能体跨会话记住的内容,可手动编辑。',
                        style:
                            TextStyle(color: AppTheme.muted, fontSize: 13)),
                    const SizedBox(height: 12),
                    Expanded(
                      child: TextField(
                        controller: _ctrl,
                        maxLines: null,
                        expands: true,
                        textAlignVertical: TextAlignVertical.top,
                        decoration: const InputDecoration(
                          hintText: '还没有记忆内容…',
                          alignLabelWithHint: true,
                        ),
                      ),
                    ),
                    const SizedBox(height: 12),
                    SizedBox(
                      width: double.infinity,
                      child: FilledButton(
                        onPressed: _saving ? null : _save,
                        child: Text(_saving ? '保存中…' : '保存'),
                      ),
                    ),
                  ]),
            ),
    );
  }
}
