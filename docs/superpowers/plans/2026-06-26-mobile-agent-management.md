# Flutter App Agent 管理(创建 + 设置)Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为 `apps/mobile` 补齐「创建 agent」与「设置 agent」(名称/人设AGENTS/工具入口/技能入口/agent记忆/删除),与 web 对齐。

**Architecture:** 纯 app 端,后端零改动(端点全现成)。数据层补 createAgent/patchAgentName + ContextDocument(AGENTS) + agent-scope memory 三组 repository 方法;UI 层新增 Agent 设置页(单页聚合)与 Agent 记忆页,home 加创建入口 + 长按管理菜单。照 app 现有 Riverpod + Dio repository + go_router + AppTheme 模式。

**Tech Stack:** Flutter / Riverpod / Dio(`http_mock_adapter` 测) / go_router。spec: `docs/superpowers/specs/2026-06-26-mobile-agent-management-design.md`。

**工作目录:** `.worktrees/feat-mobile-agent-mgmt`。所有命令在 `apps/mobile/` 下跑(`flutter test`)。

---

## File Structure

| 文件 | 职责 | 改/建 |
|---|---|---|
| `lib/features/sessions/sessions_repository.dart` | +`createAgent`/`patchAgentName` | 改 |
| `lib/features/sessions/sessions_controller.dart` | +`createAgent`/`renameAgent`(invalidate agentsProvider) | 改 |
| `lib/models/context_document.dart` | ContextDocument model | 建 |
| `lib/features/agent/agent_repository.dart` | +AGENTS 读写 + agent-scope memory 读写清 | 改 |
| `lib/features/agent/agent_memory_page.dart` | agent 专属记忆页 | 建 |
| `lib/features/agent/agent_settings_page.dart` | agent 设置页(名称/人设/导航行/删除) | 建 |
| `lib/core/router/app_router.dart` | +`/agent/:aid/settings`、`/agent/:aid/memory` | 改 |
| `lib/features/sessions/home_page.dart` | +创建入口 + 长按管理菜单 + 空态文案 | 改 |

YAGNI:`AgentConfig` 不补 `permissions`(无 UI、fromJson 忽略额外字段);模型/凭据不进 agent 页(session 级,已有)。

---

## Task 1: Agent 创建 + 重命名(数据层)

**Files:**
- Modify: `lib/features/sessions/sessions_repository.dart`(`deleteAgent` 后追加)
- Modify: `lib/features/sessions/sessions_controller.dart`(`SessionsController` 内 `deleteAgent` 后追加)
- Test: `test/features/sessions/sessions_repository_test.dart`(追加)

- [ ] **Step 1: 写失败测试**(追加到 test 文件 `main()` 内)

```dart
  test('createAgent POST + 解析', () async {
    final dio = Dio(BaseOptions(baseUrl: 'http://x/api'));
    DioAdapter(dio: dio).onPost('/agent-configs',
        (s) => s.reply(201, {'id': 'a9', 'name': 'Agent 2'}),
        data: {'name': 'Agent 2'});
    final a = await SessionsRepository(dio).createAgent('Agent 2');
    expect(a.id, 'a9');
    expect(a.name, 'Agent 2');
  });

  test('patchAgentName PATCH + 解析', () async {
    final dio = Dio(BaseOptions(baseUrl: 'http://x/api'));
    DioAdapter(dio: dio).onPatch('/agent-configs/a1',
        (s) => s.reply(200, {'id': 'a1', 'name': '客服'}),
        data: {'name': '客服'});
    final a = await SessionsRepository(dio).patchAgentName('a1', '客服');
    expect(a.name, '客服');
  });
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd apps/mobile && flutter test test/features/sessions/sessions_repository_test.dart`
Expected: FAIL(`createAgent`/`patchAgentName` 未定义)

- [ ] **Step 3: 实现 repository 方法**(在 `sessions_repository.dart` 的 `deleteAgent` 行后):

```dart
  // 创建 agent:后端只需 name,返回完整 AgentConfig。
  Future<AgentConfig> createAgent(String name) async {
    final r = await _dio.post('/agent-configs', data: {'name': name});
    return AgentConfig.fromJson(r.data as Map<String, dynamic>);
  }

  // 重命名 agent(PATCH name)。
  Future<AgentConfig> patchAgentName(String id, String name) async {
    final r = await _dio.patch('/agent-configs/$id', data: {'name': name});
    return AgentConfig.fromJson(r.data as Map<String, dynamic>);
  }
```

- [ ] **Step 4: 实现 controller 方法**(在 `sessions_controller.dart` 的 `SessionsController.deleteAgent` 方法后):

```dart
  /// 创建 agent → 刷新 agent 列表 → 返回新 agent(供调用方选中 + 跳设置页)。
  Future<AgentConfig> createAgent(String name) async {
    final a = await ref.read(sessionsRepoProvider).createAgent(name);
    ref.invalidate(agentsProvider);
    return a;
  }

  /// 重命名 agent → 刷新 agent 列表。
  Future<void> renameAgent(String id, String name) async {
    await ref.read(sessionsRepoProvider).patchAgentName(id, name);
    ref.invalidate(agentsProvider);
  }
```

- [ ] **Step 5: 跑测试确认通过 + 类型检查**

Run: `cd apps/mobile && flutter test test/features/sessions/sessions_repository_test.dart && flutter analyze`
Expected: PASS,analyze 无 issue

- [ ] **Step 6: Commit**

```bash
git add apps/mobile/lib/features/sessions/sessions_repository.dart apps/mobile/lib/features/sessions/sessions_controller.dart apps/mobile/test/features/sessions/sessions_repository_test.dart
git commit -m "feat(mobile): agent 创建 + 重命名(数据层)"
```

---

## Task 2: ContextDocument model + AGENTS 人设(数据层)

**Files:**
- Create: `lib/models/context_document.dart`
- Modify: `lib/features/agent/agent_repository.dart`(顶部 import + `AgentRepository` 内追加)
- Test: `test/features/agent/agent_repository_test.dart`(新建)

- [ ] **Step 1: 写 ContextDocument model**(`lib/models/context_document.dart`):

```dart
class ContextDocument {
  final String id;
  final String scope;
  final String type;
  final String content;

  const ContextDocument({
    required this.id,
    required this.scope,
    required this.type,
    required this.content,
  });

  factory ContextDocument.fromJson(Map<String, dynamic> j) => ContextDocument(
        id: j['id'] as String,
        scope: j['scope'] as String,
        type: j['type'] as String,
        content: j['content'] as String? ?? '',
      );
}
```

- [ ] **Step 2: 写失败测试**(`test/features/agent/agent_repository_test.dart` 新建):

```dart
import 'package:dio/dio.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http_mock_adapter/http_mock_adapter.dart';
import 'package:agent_cloud_mobile/features/agent/agent_repository.dart';

void main() {
  test('getAgentInstructions 取 AGENTS content', () async {
    final dio = Dio(BaseOptions(baseUrl: 'http://x/api'));
    DioAdapter(dio: dio).onGet('/context-documents',
        (s) => s.reply(200, [
              {'id': 'd1', 'scope': 'agent', 'type': 'AGENTS', 'owner_id': 'a1', 'content': '你是客服'},
            ]),
        queryParameters: {'scope': 'agent', 'agent_id': 'a1'});
    expect(await AgentRepository(dio).getAgentInstructions('a1'), '你是客服');
  });

  test('getAgentInstructions 无 AGENTS → 空串', () async {
    final dio = Dio(BaseOptions(baseUrl: 'http://x/api'));
    DioAdapter(dio: dio).onGet('/context-documents',
        (s) => s.reply(200, []),
        queryParameters: {'scope': 'agent', 'agent_id': 'a1'});
    expect(await AgentRepository(dio).getAgentInstructions('a1'), '');
  });

  test('putAgentInstructions PUT body', () async {
    final dio = Dio(BaseOptions(baseUrl: 'http://x/api'));
    DioAdapter(dio: dio).onPut('/context-documents',
        (s) => s.reply(200, {'id': 'd1', 'scope': 'agent', 'type': 'AGENTS', 'owner_id': 'a1', 'content': 'x'}),
        data: {'scope': 'agent', 'type': 'AGENTS', 'content': 'x', 'agent_id': 'a1'});
    await AgentRepository(dio).putAgentInstructions('a1', 'x');
  });
}
```

- [ ] **Step 3: 跑测试确认失败**

Run: `cd apps/mobile && flutter test test/features/agent/agent_repository_test.dart`
Expected: FAIL(`getAgentInstructions`/`putAgentInstructions` 未定义)

- [ ] **Step 4: 实现**(在 `agent_repository.dart` 顶部加 import,`AgentRepository` 内 `setAgentSkills` 后加方法):

import 行:
```dart
import '../../models/context_document.dart';
```
方法:
```dart
  /// agent 人设(AGENTS 文档)内容;无则空串。
  Future<String> getAgentInstructions(String agentId) async {
    final r = await _dio.get('/context-documents',
        queryParameters: {'scope': 'agent', 'agent_id': agentId});
    final docs = (r.data as List)
        .map((e) => ContextDocument.fromJson(e as Map<String, dynamic>))
        .where((d) => d.type == 'AGENTS');
    return docs.isEmpty ? '' : docs.first.content;
  }

  /// 写 agent 人设(AGENTS)。
  Future<void> putAgentInstructions(String agentId, String content) =>
      _dio.put('/context-documents', data: {
        'scope': 'agent',
        'type': 'AGENTS',
        'content': content,
        'agent_id': agentId,
      });
```

- [ ] **Step 5: 跑测试确认通过 + analyze**

Run: `cd apps/mobile && flutter test test/features/agent/agent_repository_test.dart && flutter analyze`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add apps/mobile/lib/models/context_document.dart apps/mobile/lib/features/agent/agent_repository.dart apps/mobile/test/features/agent/agent_repository_test.dart
git commit -m "feat(mobile): agent 人设(AGENTS 文档)读写(数据层)"
```

---

## Task 3: Agent 专属记忆(数据层)

**Files:**
- Modify: `lib/features/agent/agent_repository.dart`(追加 3 方法)
- Test: `test/features/agent/agent_repository_test.dart`(追加)

- [ ] **Step 1: 写失败测试**(追加到 `agent_repository_test.dart` `main()`):

```dart
  test('getAgentMemory 取 content', () async {
    final dio = Dio(BaseOptions(baseUrl: 'http://x/api'));
    DioAdapter(dio: dio).onGet('/memory',
        (s) => s.reply(200, {'scope': 'agent', 'owner_id': 'a1', 'content': '偏好简洁', 'version': 1}),
        queryParameters: {'scope': 'agent', 'agent_id': 'a1'});
    expect(await AgentRepository(dio).getAgentMemory('a1'), '偏好简洁');
  });

  test('putAgentMemory PUT body', () async {
    final dio = Dio(BaseOptions(baseUrl: 'http://x/api'));
    DioAdapter(dio: dio).onPut('/memory',
        (s) => s.reply(200, {'scope': 'agent', 'owner_id': 'a1', 'content': 'x', 'version': 2}),
        data: {'scope': 'agent', 'content': 'x', 'agent_id': 'a1'});
    await AgentRepository(dio).putAgentMemory('a1', 'x');
  });

  test('clearAgentMemory DELETE query', () async {
    final dio = Dio(BaseOptions(baseUrl: 'http://x/api'));
    DioAdapter(dio: dio).onDelete('/memory',
        (s) => s.reply(200, {'scope': 'agent', 'owner_id': 'a1', 'content': '', 'version': 3}),
        queryParameters: {'scope': 'agent', 'agent_id': 'a1'});
    await AgentRepository(dio).clearAgentMemory('a1');
  });
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd apps/mobile && flutter test test/features/agent/agent_repository_test.dart`
Expected: FAIL(三方法未定义)

- [ ] **Step 3: 实现**(在 `agent_repository.dart` `putAgentInstructions` 后):

```dart
  /// agent 专属记忆(scope=agent)读;无则空串。
  Future<String> getAgentMemory(String agentId) async {
    final r = await _dio.get('/memory',
        queryParameters: {'scope': 'agent', 'agent_id': agentId});
    return (r.data as Map<String, dynamic>)['content'] as String? ?? '';
  }

  Future<void> putAgentMemory(String agentId, String content) =>
      _dio.put('/memory',
          data: {'scope': 'agent', 'content': content, 'agent_id': agentId});

  Future<void> clearAgentMemory(String agentId) => _dio.delete('/memory',
      queryParameters: {'scope': 'agent', 'agent_id': agentId});
```

- [ ] **Step 4: 跑测试确认通过 + analyze**

Run: `cd apps/mobile && flutter test test/features/agent/agent_repository_test.dart && flutter analyze`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add apps/mobile/lib/features/agent/agent_repository.dart apps/mobile/test/features/agent/agent_repository_test.dart
git commit -m "feat(mobile): agent 专属记忆读写清(数据层)"
```

---

## Task 4: Agent 记忆页

**Files:**
- Create: `lib/features/agent/agent_memory_page.dart`
- Test: `test/features/agent/agent_memory_page_test.dart`

照 `lib/features/settings/memory_page.dart` 结构,改为 agent-scope(用 Task 3 的 `agentRepoProvider` 方法,带 agentId)。

- [ ] **Step 1: 实现页面**(`lib/features/agent/agent_memory_page.dart`):

```dart
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
      _ctrl.text = await ref.read(agentRepoProvider).getAgentMemory(widget.agentId);
    } catch (_) {}
    if (mounted) setState(() => _loading = false);
  }

  Future<void> _save() async {
    setState(() => _saving = true);
    try {
      await ref.read(agentRepoProvider).putAgentMemory(widget.agentId, _ctrl.text.trim());
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('已保存')));
      }
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('保存失败: $e')));
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
          TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('取消')),
          TextButton(
              onPressed: () => Navigator.pop(ctx, true),
              child: const Text('清除', style: TextStyle(color: AppTheme.danger))),
        ],
      ),
    );
    if (ok != true) return;
    try {
      await ref.read(agentRepoProvider).clearAgentMemory(widget.agentId);
      _ctrl.clear();
      if (mounted) setState(() {});
    } catch (_) {}
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
          : Padding(
              padding: const EdgeInsets.all(16),
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                const Text('这个智能体跨会话记住的内容,可手动编辑。',
                    style: TextStyle(color: AppTheme.muted, fontSize: 13)),
                const SizedBox(height: 12),
                Expanded(
                  child: TextField(
                    controller: _ctrl,
                    maxLines: null,
                    expands: true,
                    textAlignVertical: TextAlignVertical.top,
                    decoration: const InputDecoration(
                        hintText: '还没有记忆内容…', alignLabelWithHint: true),
                  ),
                ),
                const SizedBox(height: 12),
                SizedBox(
                  width: double.infinity,
                  child: FilledButton(
                      onPressed: _saving ? null : _save,
                      child: Text(_saving ? '保存中…' : '保存')),
                ),
              ]),
            ),
    );
  }
}
```

- [ ] **Step 2: 写 widget 测试**(`test/features/agent/agent_memory_page_test.dart`):

```dart
import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:http_mock_adapter/http_mock_adapter.dart';
import 'package:agent_cloud_mobile/features/agent/agent_memory_page.dart';
import 'package:agent_cloud_mobile/features/agent/agent_repository.dart';
import 'package:agent_cloud_mobile/features/auth/auth_controller.dart';

Dio _dio() {
  final dio = Dio(BaseOptions(baseUrl: 'http://x/api'));
  DioAdapter(dio: dio)
    ..onGet('/memory',
        (s) => s.reply(200, {'scope': 'agent', 'owner_id': 'a1', 'content': '记得偏好', 'version': 1}),
        queryParameters: {'scope': 'agent', 'agent_id': 'a1'});
  return dio;
}

void main() {
  testWidgets('加载并显示 agent 记忆内容', (tester) async {
    await tester.pumpWidget(ProviderScope(
      overrides: [dioProvider.overrideWithValue(_dio())],
      child: const MaterialApp(home: AgentMemoryPage('a1')),
    ));
    await tester.pumpAndSettle();
    expect(find.text('记得偏好'), findsOneWidget);
    expect(find.text('保存'), findsOneWidget);
  });
}
```

- [ ] **Step 3: 跑测试 + analyze**

Run: `cd apps/mobile && flutter test test/features/agent/agent_memory_page_test.dart && flutter analyze`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add apps/mobile/lib/features/agent/agent_memory_page.dart apps/mobile/test/features/agent/agent_memory_page_test.dart
git commit -m "feat(mobile): agent 专属记忆页"
```

---

## Task 5: Agent 设置页

**Files:**
- Create: `lib/features/agent/agent_settings_page.dart`
- Test: `test/features/agent/agent_settings_page_test.dart`

聚合:名称(行内可编辑)+ 人设 AGENTS(textarea + 保存,套 web "空且无原文档则不写"约束)+ 配置导航行(工具/技能/记忆)+ 删除(复用 home 的 409 处理逻辑,这里简化为 controller.deleteAgent + pop)。

- [ ] **Step 1: 实现页面**(`lib/features/agent/agent_settings_page.dart`):

```dart
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
      final text = await ref.read(agentRepoProvider).getAgentInstructions(widget.agentId);
      _instructions.text = text;
      _hadDoc = text.isNotEmpty;
    } catch (_) {}
    if (mounted) setState(() => _loading = false);
  }

  Future<void> _save() async {
    final name = _name.text.trim();
    if (name.isEmpty) {
      ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('名称不能为空')));
      return;
    }
    setState(() => _saving = true);
    try {
      await ref.read(sessionsControllerProvider.notifier).renameAgent(widget.agentId, name);
      final text = _instructions.text;
      // 非空,或原本有文档(持久化"清空") → 写入;否则不创建空文档。
      if (text.trim().isNotEmpty || _hadDoc) {
        await ref.read(agentRepoProvider).putAgentInstructions(widget.agentId, text);
        _hadDoc = true;
      }
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('已保存')));
      }
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('保存失败: $e')));
      }
    }
    if (mounted) setState(() => _saving = false);
  }

  Future<void> _delete() async {
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: Text('删除「${_name.text.trim()}」?'),
        content: const Text('将连同该智能体的全部会话一起删除,不可恢复。'),
        actions: [
          TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('取消')),
          TextButton(
              onPressed: () => Navigator.pop(ctx, true),
              child: const Text('删除', style: TextStyle(color: AppTheme.danger))),
        ],
      ),
    );
    if (ok != true) return;
    try {
      await ref.read(sessionsControllerProvider.notifier).deleteAgent(widget.agentId);
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
            style: const TextStyle(fontWeight: FontWeight.w500, color: AppTheme.ink)),
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
                    style: TextStyle(fontSize: 13, fontWeight: FontWeight.w600, color: AppTheme.muted)),
              ),
              TextField(controller: _name, decoration: const InputDecoration(hintText: '智能体名称')),
              const SizedBox(height: 20),
              const Padding(
                padding: EdgeInsets.only(left: 4, bottom: 8),
                child: Text('人设 / 指令',
                    style: TextStyle(fontSize: 13, fontWeight: FontWeight.w600, color: AppTheme.muted)),
              ),
              TextField(
                controller: _instructions,
                maxLines: 6,
                decoration: const InputDecoration(hintText: '描述这个智能体的角色、语气、行为准则…'),
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
                    style: TextStyle(fontSize: 13, fontWeight: FontWeight.w600, color: AppTheme.muted)),
              ),
              Container(
                decoration: BoxDecoration(
                  color: AppTheme.surface,
                  borderRadius: BorderRadius.circular(AppTheme.rCard),
                  border: Border.all(color: AppTheme.border),
                ),
                child: Column(children: [
                  _navTile(Icons.build_outlined, '工具', '/agent/${widget.agentId}/tools'),
                  const Divider(height: 1, indent: 52),
                  _navTile(Icons.extension_outlined, '技能', '/agent/${widget.agentId}/skills'),
                  const Divider(height: 1, indent: 52),
                  _navTile(Icons.psychology_outlined, '记忆', '/agent/${widget.agentId}/memory'),
                ]),
              ),
              const SizedBox(height: 24),
              OutlinedButton.icon(
                onPressed: _delete,
                icon: const Icon(Icons.delete_outline, color: AppTheme.danger),
                label: const Text('删除此 Agent', style: TextStyle(color: AppTheme.danger)),
                style: OutlinedButton.styleFrom(side: const BorderSide(color: AppTheme.danger)),
              ),
            ]),
    );
  }
}
```

- [ ] **Step 2: 写 widget 测试**(`test/features/agent/agent_settings_page_test.dart`):

```dart
import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:http_mock_adapter/http_mock_adapter.dart';
import 'package:agent_cloud_mobile/features/agent/agent_settings_page.dart';
import 'package:agent_cloud_mobile/features/auth/auth_controller.dart';
import 'package:agent_cloud_mobile/features/sessions/sessions_controller.dart';
import 'package:agent_cloud_mobile/models/agent_config.dart';

Dio _dio() {
  final dio = Dio(BaseOptions(baseUrl: 'http://x/api'));
  DioAdapter(dio: dio).onGet('/context-documents',
      (s) => s.reply(200, [
            {'id': 'd1', 'scope': 'agent', 'type': 'AGENTS', 'owner_id': 'a1', 'content': '你是客服'},
          ]),
      queryParameters: {'scope': 'agent', 'agent_id': 'a1'});
  return dio;
}

void main() {
  testWidgets('显示名称 + 人设 + 三个配置入口 + 删除', (tester) async {
    await tester.pumpWidget(ProviderScope(
      overrides: [
        dioProvider.overrideWithValue(_dio()),
        agentsProvider.overrideWith((ref) =>
            Future.value([const AgentConfig(id: 'a1', name: '客服助手')])),
      ],
      child: const MaterialApp(home: AgentSettingsPage('a1')),
    ));
    await tester.pumpAndSettle();
    expect(find.text('客服助手'), findsOneWidget); // 名称
    expect(find.text('你是客服'), findsOneWidget); // 人设
    expect(find.text('工具'), findsOneWidget);
    expect(find.text('技能'), findsOneWidget);
    expect(find.text('记忆'), findsOneWidget);
    expect(find.text('删除此 Agent'), findsOneWidget);
  });
}
```

- [ ] **Step 3: 跑测试 + analyze**

Run: `cd apps/mobile && flutter test test/features/agent/agent_settings_page_test.dart && flutter analyze`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add apps/mobile/lib/features/agent/agent_settings_page.dart apps/mobile/test/features/agent/agent_settings_page_test.dart
git commit -m "feat(mobile): agent 设置页(名称/人设/工具技能记忆入口/删除)"
```

---

## Task 6: 路由 + home 创建入口 + 长按管理菜单

**Files:**
- Modify: `lib/core/router/app_router.dart`(+2 路由 + import)
- Modify: `lib/features/sessions/home_page.dart`(创建入口 + 长按菜单 + 空态文案)
- Test: `test/features/sessions/home_page_test.dart`(新建,验证创建入口)

- [ ] **Step 1: 加路由**(`app_router.dart`,在 `/agent/:aid/skills` 路由后加,顶部加 import):

import:
```dart
import '../../features/agent/agent_settings_page.dart';
import '../../features/agent/agent_memory_page.dart';
```
路由:
```dart
      GoRoute(
          path: '/agent/:aid/settings',
          builder: (_, st) => AgentSettingsPage(st.pathParameters['aid']!)),
      GoRoute(
          path: '/agent/:aid/memory',
          builder: (_, st) => AgentMemoryPage(st.pathParameters['aid']!)),
```

- [ ] **Step 2: home 长按菜单改造**(`home_page.dart`):把 `_agentBar` 里 `onLongPress: () => _deleteAgent(a)` 改为 `onLongPress: () => _agentActions(a)`,并新增 `_agentActions` 方法(照 `_showActions` 模板,加「设置」+「删除」):

```dart
  void _agentActions(AgentConfig a) {
    showModalBottomSheet(
      context: context,
      shape: const RoundedRectangleBorder(
          borderRadius: BorderRadius.vertical(top: Radius.circular(20))),
      builder: (_) => SafeArea(
        child: Column(mainAxisSize: MainAxisSize.min, children: [
          ListTile(
            leading: const Icon(Icons.settings_outlined),
            title: const Text('设置'),
            onTap: () {
              Navigator.pop(context);
              context.push('/agent/${a.id}/settings');
            },
          ),
          ListTile(
            leading: const Icon(Icons.delete_outline, color: AppTheme.danger),
            title: const Text('删除', style: TextStyle(color: AppTheme.danger)),
            onTap: () {
              Navigator.pop(context);
              _deleteAgent(a);
            },
          ),
          const SizedBox(height: 8),
        ]),
      ),
    );
  }
```

- [ ] **Step 3: home 创建入口**(`home_page.dart`):在 `_agentBar` 的 `ListView.separated` 把 `itemCount: agents.length` 改为 `itemCount: agents.length + 1`,`itemBuilder` 开头加末位 `+` chip:

```dart
        itemBuilder: (_, i) {
          if (i == agents.length) {
            return GestureDetector(
              onTap: _createAgent,
              child: Container(
                padding: const EdgeInsets.symmetric(horizontal: 14),
                alignment: Alignment.center,
                decoration: BoxDecoration(
                  color: AppTheme.surface,
                  borderRadius: BorderRadius.circular(20),
                  border: Border.all(color: AppTheme.border),
                ),
                child: const Icon(Icons.add, size: 18, color: AppTheme.muted),
              ),
            );
          }
          final a = agents[i];
          // ...(原有 chip 代码不变)
```

新增 `_createAgent`(弹填名 dialog → 创建 → 跳设置页):
```dart
  Future<void> _createAgent() async {
    final ctrl = TextEditingController();
    final name = await showDialog<String>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('新建智能体'),
        content: TextField(
          controller: ctrl,
          autofocus: true,
          decoration: const InputDecoration(hintText: '智能体名称'),
          onSubmitted: (v) => Navigator.pop(ctx, v.trim()),
        ),
        actions: [
          TextButton(onPressed: () => Navigator.pop(ctx), child: const Text('取消')),
          FilledButton(
              onPressed: () => Navigator.pop(ctx, ctrl.text.trim()),
              child: const Text('创建')),
        ],
      ),
    );
    ctrl.dispose();
    if (name == null || name.isEmpty) return;
    try {
      final a = await ref.read(sessionsControllerProvider.notifier).createAgent(name);
      if (mounted) {
        setState(() => _selectedAgentId = a.id);
        context.push('/agent/${a.id}/settings');
      }
    } catch (e) {
      _toast('创建失败: $e');
    }
  }
```

- [ ] **Step 4: 空态文案 + 空态可创建**(`home_page.dart`):把 `_empty('还没有智能体', '在 web 端创建一个智能体后即可开始')` 改为可点创建。最小改:文案改为 `_empty('还没有智能体', '点右上角或下方按钮创建')`;并在 `build` 的 `body` Column,当 `agents.isEmpty` 时也显示一个创建入口——简化为在 AppBar 加一个 `+` action:

在 home 的 `AppBar` actions 里加(若已有 actions 则追加):
```dart
          IconButton(
              onPressed: _createAgent,
              icon: const Icon(Icons.add),
              tooltip: '新建智能体'),
```
并把空态文案改为:
```dart
        _empty('还没有智能体', '点右上角 + 新建一个开始')
```

- [ ] **Step 5: 写创建入口 widget 测试**(`test/features/sessions/home_page_test.dart`):

```dart
import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:http_mock_adapter/http_mock_adapter.dart';
import 'package:agent_cloud_mobile/features/sessions/home_page.dart';
import 'package:agent_cloud_mobile/features/auth/auth_controller.dart';
import 'package:agent_cloud_mobile/features/sessions/sessions_controller.dart';
import 'package:agent_cloud_mobile/models/agent_config.dart';

Dio _dio() {
  final dio = Dio(BaseOptions(baseUrl: 'http://x/api'));
  DioAdapter(dio: dio).onGet('/sessions', (s) => s.reply(200, []));
  return dio;
}

void main() {
  testWidgets('agent 栏末尾有 + 创建入口', (tester) async {
    await tester.pumpWidget(ProviderScope(
      overrides: [
        dioProvider.overrideWithValue(_dio()),
        agentsProvider.overrideWith((ref) =>
            Future.value([const AgentConfig(id: 'a1', name: 'main')])),
      ],
      child: const MaterialApp(home: HomePage()),
    ));
    await tester.pumpAndSettle();
    // agent chip + 末位创建按钮(Icons.add 在 chip 栏)
    expect(find.byIcon(Icons.add), findsWidgets);
  });
}
```

- [ ] **Step 6: 跑测试 + analyze**

Run: `cd apps/mobile && flutter test test/features/sessions/home_page_test.dart && flutter analyze`
Expected: PASS

- [ ] **Step 7: 全量回归 + Commit**

```bash
cd apps/mobile && flutter test && flutter analyze
git add apps/mobile/lib/core/router/app_router.dart apps/mobile/lib/features/sessions/home_page.dart apps/mobile/test/features/sessions/home_page_test.dart
git commit -m "feat(mobile): 路由 + home 创建入口 + agent 长按管理菜单"
```

---

## 验收(全部任务后)

- [ ] `cd apps/mobile && flutter test`(全绿)+ `flutter analyze`(无 issue)。
- [ ] 手动走查:home 点 `+` → 填名 → 进设置页 → 改名/写人设/保存 → 工具/技能/记忆入口跳转 → 删除回退。
- [ ] 对抗式 code review(子 agent)。

## 任务依赖
Task 1/2/3(数据层,可并行)→ Task 4(依赖 3)、Task 5(依赖 1/2)→ Task 6(依赖 4/5 的页面 + 路由)。建议顺序 1→2→3→4→5→6。
