import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:image_picker/image_picker.dart';
import '../../core/theme/app_theme.dart';
import '../../models/file_entry.dart';
import 'files_repository.dart';

const _imgExt = {'png', 'jpg', 'jpeg', 'webp', 'gif', 'bmp'};
const _docExt = {
  'pdf', 'doc', 'docx', 'xls', 'xlsx', 'ppt', 'pptx',
  'csv', 'txt', 'md', 'json', 'log', 'yaml', 'yml'
};

/// 工作区文件浏览器:目录导航 + 预览 + 删除 + 新建文件夹 + 上传图片。
class FilesPage extends ConsumerStatefulWidget {
  const FilesPage({super.key});
  @override
  ConsumerState<FilesPage> createState() => _FilesPageState();
}

class _FilesPageState extends ConsumerState<FilesPage> {
  String _path = ''; // 当前目录(根 = 空)

  bool get _atRoot => _path.isEmpty;
  void _enter(String dir) => setState(() => _path = dir);
  void _up() {
    final i = _path.lastIndexOf('/');
    setState(() => _path = i < 0 ? '' : _path.substring(0, i));
  }

  void _refresh() => ref.invalidate(filesListProvider(_path));

  Future<void> _upload() async {
    final imgs = await ImagePicker().pickMultiImage();
    if (imgs.isEmpty) return;
    try {
      await ref.read(filesRepoProvider).uploadImages(imgs, dir: _path);
      _refresh();
    } catch (e) {
      _toast('上传失败: $e');
    }
  }

  Future<void> _mkdir() async {
    final ctrl = TextEditingController();
    final name = await showDialog<String>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('新建文件夹'),
        content: TextField(
            controller: ctrl,
            autofocus: true,
            decoration: const InputDecoration(hintText: '名称')),
        actions: [
          TextButton(
              onPressed: () => Navigator.pop(ctx), child: const Text('取消')),
          FilledButton(
              onPressed: () => Navigator.pop(ctx, ctrl.text.trim()),
              child: const Text('创建')),
        ],
      ),
    );
    ctrl.dispose();
    if (name == null || name.isEmpty) return;
    try {
      await ref
          .read(filesRepoProvider)
          .mkdir(_path.isEmpty ? name : '$_path/$name');
      _refresh();
    } catch (e) {
      _toast('创建失败: $e');
    }
  }

  Future<bool> _confirmDelete(FileEntry e) async {
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: Text('删除 ${e.name}?'),
        content: Text(e.isDir ? '将删除该文件夹及其内容。' : '此操作不可撤销。'),
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
    if (ok != true) return false;
    try {
      await ref.read(filesRepoProvider).delete(e.path);
      _refresh();
    } catch (err) {
      _toast('删除失败: $err');
    }
    return false; // 靠 provider 刷新移除,不本地 dismiss
  }

  void _open(FileEntry e) {
    if (e.isDir) {
      _enter(e.path);
      return;
    }
    final ext = e.name.toLowerCase().split('.').last;
    if (_imgExt.contains(ext)) {
      showDialog(context: context, builder: (_) => _ImagePreview(e));
    } else if (_docExt.contains(ext)) {
      showDialog(context: context, builder: (_) => _TextPreview(e));
    } else {
      _toast('暂不支持预览 .$ext');
    }
  }

  void _toast(String m) {
    if (mounted) {
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(m)));
    }
  }

  @override
  Widget build(BuildContext context) {
    final files = ref.watch(filesListProvider(_path));
    return Scaffold(
      appBar: AppBar(
        title: Text(_atRoot ? '文件' : _path.split('/').last),
        leading: _atRoot
            ? null
            : IconButton(icon: const Icon(Icons.arrow_back), onPressed: _up),
        actions: [
          IconButton(
              icon: const Icon(Icons.create_new_folder_outlined),
              tooltip: '新建文件夹',
              onPressed: _mkdir),
          IconButton(
              icon: const Icon(Icons.add_photo_alternate_outlined),
              tooltip: '上传图片',
              onPressed: _upload),
        ],
      ),
      body: files.when(
        loading: () => const Center(child: CircularProgressIndicator()),
        error: (e, _) => Center(child: Text('加载失败: $e')),
        data: (list) {
          final sorted = [...list]..sort((a, b) {
              if (a.isDir != b.isDir) return a.isDir ? -1 : 1;
              return a.name.toLowerCase().compareTo(b.name.toLowerCase());
            });
          return RefreshIndicator(
            onRefresh: () async => _refresh(),
            child: sorted.isEmpty
                ? ListView(children: const [
                    SizedBox(height: 140),
                    Center(
                        child: Text('空目录',
                            style: TextStyle(color: AppTheme.muted))),
                  ])
                : ListView.separated(
                    itemCount: sorted.length,
                    separatorBuilder: (_, _) =>
                        const Divider(height: 1, indent: 56),
                    itemBuilder: (_, i) => _row(sorted[i]),
                  ),
          );
        },
      ),
    );
  }

  Widget _row(FileEntry e) => Dismissible(
        key: ValueKey(e.path),
        direction: DismissDirection.endToStart,
        background: Container(
          color: AppTheme.dangerSoft,
          alignment: Alignment.centerRight,
          padding: const EdgeInsets.only(right: 20),
          child: const Icon(Icons.delete_outline, color: AppTheme.danger),
        ),
        confirmDismiss: (_) => _confirmDelete(e),
        child: ListTile(
          leading: Icon(e.isDir ? Icons.folder : _fileIcon(e.name),
              color: e.isDir ? AppTheme.teal : AppTheme.faint),
          title:
              Text(e.name, maxLines: 1, overflow: TextOverflow.ellipsis),
          subtitle: e.isDir
              ? null
              : Text(e.prettySize,
                  style: const TextStyle(fontSize: 12, color: AppTheme.faint)),
          trailing: e.isDir
              ? const Icon(Icons.chevron_right, color: AppTheme.faint)
              : null,
          onTap: () => _open(e),
        ),
      );

  IconData _fileIcon(String name) {
    final ext = name.toLowerCase().split('.').last;
    if (_imgExt.contains(ext)) return Icons.image_outlined;
    if (ext == 'pdf') return Icons.picture_as_pdf_outlined;
    if (['doc', 'docx', 'txt', 'md'].contains(ext)) {
      return Icons.description_outlined;
    }
    if (['xls', 'xlsx', 'csv'].contains(ext)) {
      return Icons.table_chart_outlined;
    }
    return Icons.insert_drive_file_outlined;
  }
}

/// 图片预览弹窗(带 token 取字节)。
class _ImagePreview extends ConsumerWidget {
  final FileEntry entry;
  const _ImagePreview(this.entry);
  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final img = ref.watch(sentImageProvider(entry.path));
    return Dialog(
      child: Column(mainAxisSize: MainAxisSize.min, children: [
        AppBar(
          title: Text(entry.name,
              maxLines: 1, overflow: TextOverflow.ellipsis),
          automaticallyImplyLeading: false,
          actions: [
            IconButton(
                icon: const Icon(Icons.close),
                onPressed: () => Navigator.pop(context))
          ],
        ),
        Flexible(
          child: img.when(
            loading: () => const Padding(
                padding: EdgeInsets.all(40),
                child: CircularProgressIndicator()),
            error: (e, _) => Padding(
                padding: const EdgeInsets.all(24),
                child: Text('加载失败: $e')),
            data: (bytes) => InteractiveViewer(child: Image.memory(bytes)),
          ),
        ),
      ]),
    );
  }
}

/// 文档文本预览(抽取文本)。
class _TextPreview extends ConsumerStatefulWidget {
  final FileEntry entry;
  const _TextPreview(this.entry);
  @override
  ConsumerState<_TextPreview> createState() => _TextPreviewState();
}

class _TextPreviewState extends ConsumerState<_TextPreview> {
  late final Future<String> _future =
      ref.read(filesRepoProvider).extractText(widget.entry.path);

  @override
  Widget build(BuildContext context) {
    return Dialog(
      child: Column(mainAxisSize: MainAxisSize.min, children: [
        AppBar(
          title: Text(widget.entry.name,
              maxLines: 1, overflow: TextOverflow.ellipsis),
          automaticallyImplyLeading: false,
          actions: [
            IconButton(
                icon: const Icon(Icons.close),
                onPressed: () => Navigator.pop(context))
          ],
        ),
        Flexible(
          child: FutureBuilder<String>(
            future: _future,
            builder: (_, snap) {
              if (snap.connectionState != ConnectionState.done) {
                return const Padding(
                    padding: EdgeInsets.all(40),
                    child: CircularProgressIndicator());
              }
              if (snap.hasError) {
                return Padding(
                    padding: const EdgeInsets.all(24),
                    child: Text('预览失败: ${snap.error}'));
              }
              return SingleChildScrollView(
                padding: const EdgeInsets.all(16),
                child: SelectableText(
                  snap.data!.isEmpty ? '(空)' : snap.data!,
                  style: const TextStyle(fontSize: 13, height: 1.5),
                ),
              );
            },
          ),
        ),
      ]),
    );
  }
}
