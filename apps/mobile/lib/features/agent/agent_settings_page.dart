import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import '../../core/theme/app_theme.dart';
import '../sessions/sessions_controller.dart'; // agentsProvider, sessionsControllerProvider
import 'agent_repository.dart';

/// Agent 设置页:名称 / 人设(AGENTS) / 工具·技能·记忆入口 / 删除。
class AgentSettingsPage extends ConsumerStatefulWidget {
  final String agentId;
  const AgentSettingsPage(this.agentId, {super.key});
  @override
  ConsumerState<AgentSettingsPage> createState() => _AgentSettingsPageState();
}

class _AgentSettingsPageState extends ConsumerState<AgentSettingsPage> {
  final _name = TextEditingController();
  final _instructions = TextEditingController();
  bool _loading = true;
  bool _hadDoc = false; // 原本是否有 AGENTS 文档(决定清空时是否仍写入)
  bool _saving = false;

  @override
  void initState() {
    super.initState();
    _load();
  }

  @override
  void dispose() {
    _name.dispose();
    _instructions.dispose();
    super.dispose();
  }

  Future<void> _load() async {
    final agents = await ref.read(agentsProvider.future);
    final a = agents.where((x) => x.id == widget.agentId);
    _name.text = a.isEmpty ? '' : a.first.name;
    try {
      final text =
          await ref.read(agentRepoProvider).getAgentInstructions(widget.agentId);
      _instructions.text = text;
      _hadDoc = text.isNotEmpty;
    } catch (_) {}
    if (mounted) setState(() => _loading = false);
  }

  Future<void> _save() async {
    final name = _name.text.trim();
    if (name.isEmpty) {
      ScaffoldMessenger.of(context)
          .showSnackBar(const SnackBar(content: Text('名称不能为空')));
      return;
    }
    setState(() => _saving = true);
    try {
      await ref
          .read(sessionsControllerProvider.notifier)
          .renameAgent(widget.agentId, name);
      final text = _instructions.text;
      // 非空,或原本有文档(持久化"清空") → 写入;否则不创建空文档。
      if (text.trim().isNotEmpty || _hadDoc) {
        await ref
            .read(agentRepoProvider)
            .putAgentInstructions(widget.agentId, text);
        _hadDoc = true;
      }
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

  Future<void> _delete() async {
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: Text(_name.text.trim().isEmpty
            ? '删除此 Agent?'
            : '删除「${_name.text.trim()}」?'),
        content: const Text('将连同该智能体的全部会话一起删除,不可恢复。'),
        actions: [
          TextButton(
              onPressed: () => Navigator.pop(ctx, false),
              child: const Text('取消')),
          TextButton(
              onPressed: () => Navigator.pop(ctx, true),
              child: const Text('删除',
                  style: TextStyle(color: AppTheme.danger))),
        ],
      ),
    );
    if (ok != true) return;
    try {
      await ref
          .read(sessionsControllerProvider.notifier)
          .deleteAgent(widget.agentId);
      if (mounted) context.pop();
    } catch (e) {
      final busy = e is DioException && e.response?.statusCode == 409;
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
            SnackBar(content: Text(busy ? '有会话在运行,无法删除' : '删除失败: $e')));
      }
    }
  }

  Widget _navTile(IconData icon, String title, String route) => ListTile(
        leading: Icon(icon, color: AppTheme.teal),
        title: Text(title,
            style: const TextStyle(
                fontWeight: FontWeight.w500, color: AppTheme.ink)),
        trailing: const Icon(Icons.chevron_right, color: AppTheme.faint),
        onTap: () => context.push(route),
      );

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Agent 设置')),
      body: _loading
          ? const Center(child: CircularProgressIndicator())
          : ListView(padding: const EdgeInsets.all(16), children: [
              const Padding(
                padding: EdgeInsets.only(left: 4, bottom: 8),
                child: Text('名称',
                    style: TextStyle(
                        fontSize: 13,
                        fontWeight: FontWeight.w600,
                        color: AppTheme.muted)),
              ),
              TextField(
                  controller: _name,
                  decoration: const InputDecoration(hintText: '智能体名称')),
              const SizedBox(height: 20),
              const Padding(
                padding: EdgeInsets.only(left: 4, bottom: 8),
                child: Text('人设 / 指令',
                    style: TextStyle(
                        fontSize: 13,
                        fontWeight: FontWeight.w600,
                        color: AppTheme.muted)),
              ),
              TextField(
                controller: _instructions,
                maxLines: 6,
                decoration: const InputDecoration(
                    hintText: '描述这个智能体的角色、语气、行为准则…'),
              ),
              const SizedBox(height: 12),
              SizedBox(
                width: double.infinity,
                child: FilledButton(
                    onPressed: _saving ? null : _save,
                    child: Text(_saving ? '保存中…' : '保存')),
              ),
              const SizedBox(height: 24),
              const Padding(
                padding: EdgeInsets.only(left: 4, bottom: 8),
                child: Text('配置',
                    style: TextStyle(
                        fontSize: 13,
                        fontWeight: FontWeight.w600,
                        color: AppTheme.muted)),
              ),
              Container(
                decoration: BoxDecoration(
                  color: AppTheme.surface,
                  borderRadius: BorderRadius.circular(AppTheme.rCard),
                  border: Border.all(color: AppTheme.border),
                ),
                child: Column(children: [
                  _navTile(Icons.build_outlined, '工具',
                      '/agent/${widget.agentId}/tools'),
                  const Divider(height: 1, indent: 52),
                  _navTile(Icons.extension_outlined, '技能',
                      '/agent/${widget.agentId}/skills'),
                  const Divider(height: 1, indent: 52),
                  _navTile(Icons.psychology_outlined, '记忆',
                      '/agent/${widget.agentId}/memory'),
                ]),
              ),
              const SizedBox(height: 24),
              OutlinedButton.icon(
                onPressed: _delete,
                icon: const Icon(Icons.delete_outline, color: AppTheme.danger),
                label: const Text('删除此 Agent',
                    style: TextStyle(color: AppTheme.danger)),
                style: OutlinedButton.styleFrom(
                    side: const BorderSide(color: AppTheme.danger)),
              ),
            ]),
    );
  }
}
