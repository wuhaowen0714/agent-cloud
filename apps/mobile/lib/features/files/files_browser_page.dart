import 'package:flutter/material.dart';
import 'package:flutter_markdown/flutter_markdown.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:image_picker/image_picker.dart';
import 'package:path_provider/path_provider.dart';
import 'package:share_plus/share_plus.dart';
import '../../core/theme/app_theme.dart';
import '../../models/file_entry.dart';
import 'files_repository.dart';

// 文本类:取原始字节 UTF-8 解码后预览(代码 / 标记 / 配置 / 数据)。
const _textExt = {
  'txt', 'md', 'markdown', 'html', 'htm', 'xml', 'css', 'scss', 'less',
  'json', 'yaml', 'yml', 'toml', 'ini', 'csv', 'tsv', 'log', 'env',
  'conf', 'cfg', 'properties', 'gradle', 'sh', 'bash', 'zsh', 'sql',
  'py', 'js', 'mjs', 'ts', 'jsx', 'tsx', 'dart', 'go', 'rs', 'java',
  'kt', 'swift', 'c', 'cc', 'cpp', 'h', 'hpp', 'rb', 'php', 'lua', 'r', 'pl', 'scala',
};
// office:走后端 extract 抽文本。
const _officeExt = {'pdf', 'doc', 'docx', 'xls', 'xlsx', 'ppt', 'pptx'};
const _imgExt = {'png', 'jpg', 'jpeg', 'webp', 'gif', 'bmp'};
// 文本/代码靠全量取字节解码预览,超此大小改走下载(防 OOM/渲染卡顿)。
const _maxTextPreview = 2 * 1024 * 1024; // 2MB

String _extOf(String name) {
  final i = name.lastIndexOf('.');
  return i < 0 ? '' : name.substring(i + 1).toLowerCase();
}

/// 类型 → (圆角图标, 主色)。按类型上不同颜色,破"满屏绿文件夹"。
(IconData, Color) _typeStyle(FileEntry e) {
  if (e.isDir) return (Icons.folder_rounded, const Color(0xFFF59E0B)); // amber
  final x = _extOf(e.name);
  if (_imgExt.contains(x)) return (Icons.image_rounded, const Color(0xFF10B981)); // emerald
  if (x == 'pdf') return (Icons.picture_as_pdf_rounded, const Color(0xFFEF4444)); // red
  if (x == 'md' || x == 'markdown') {
    return (Icons.article_rounded, const Color(0xFF3B82F6)); // blue
  }
  if (x == 'html' || x == 'htm') {
    return (Icons.html_rounded, const Color(0xFFF97316)); // orange
  }
  if ({'json', 'yaml', 'yml', 'toml', 'xml', 'ini', 'env', 'conf', 'cfg', 'properties'}
      .contains(x)) {
    return (Icons.data_object_rounded, const Color(0xFF0EA5E9)); // sky
  }
  if ({'csv', 'tsv', 'xls', 'xlsx'}.contains(x)) {
    return (Icons.table_chart_rounded, const Color(0xFF14B8A6)); // teal
  }
  if ({'doc', 'docx'}.contains(x)) {
    return (Icons.description_rounded, const Color(0xFF2563EB)); // blue-600
  }
  if ({'ppt', 'pptx'}.contains(x)) {
    return (Icons.slideshow_rounded, const Color(0xFFE11D48)); // rose
  }
  if ({'zip', 'tar', 'gz', 'tgz', 'rar', '7z'}.contains(x)) {
    return (Icons.folder_zip_rounded, const Color(0xFFB45309)); // amber-700
  }
  if (_textExt.contains(x)) {
    return (Icons.code_rounded, const Color(0xFF8B5CF6)); // violet 代码
  }
  return (Icons.insert_drive_file_rounded, AppTheme.faint);
}

/// 工作区文件浏览器:目录导航 + 多格式预览 + 下载 + 删除 + 新建文件夹 + 上传图片。
class FilesPage extends ConsumerStatefulWidget {
  const FilesPage({super.key});
  @override
  ConsumerState<FilesPage> createState() => _FilesPageState();
}

class _FilesPageState extends ConsumerState<FilesPage> {
  String _path = ''; // 当前目录(根 = 空)
  bool _showHidden = false; // 默认隐藏 . 开头文件/夹
  final Set<String> _downloading = {}; // 下载中的 path,防重复点 + 显示进度

  bool get _atRoot => _path.isEmpty;
  void _enter(String dir) => setState(() => _path = dir);
  void _up() {
    final i = _path.lastIndexOf('/');
    setState(() => _path = i < 0 ? '' : _path.substring(0, i));
  }

  void _refresh() => ref.invalidate(filesListProvider(_path));

  void _toast(String m) {
    if (mounted) {
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(m)));
    }
  }

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

  // 下载:流式落临时文件(dio.download 分块写盘,大文件不 OOM)→ 系统分享。
  // temp 名加时间戳前缀防同名覆盖;接收方看到的名字靠 fileNameOverrides 还原成原名。
  Future<void> _download(FileEntry e) async {
    if (_downloading.contains(e.path)) return; // 防重复点
    setState(() => _downloading.add(e.path));
    _toast('下载「${e.name}」…');
    try {
      final dir = await getTemporaryDirectory();
      final savePath =
          '${dir.path}/${DateTime.now().microsecondsSinceEpoch}_${e.name}';
      await ref.read(filesRepoProvider).downloadToFile(e.path, savePath);
      await SharePlus.instance.share(ShareParams(
        files: [XFile(savePath, name: e.name)],
        fileNameOverrides: [e.name],
      ));
    } catch (err) {
      _toast('下载失败: $err');
    } finally {
      if (mounted) setState(() => _downloading.remove(e.path));
    }
  }

  void _open(FileEntry e) {
    if (e.isDir) {
      _enter(e.path);
      return;
    }
    final x = _extOf(e.name);
    final isText = _textExt.contains(x) || x == 'md' || x == 'markdown';
    // 文本/代码靠全量取字节解码,过大易 OOM/卡顿 → 超限改走下载。
    if (isText && e.size > _maxTextPreview) {
      _downloadSheet(e, '文件较大(${e.prettySize}),不便直接预览');
      return;
    }
    final repo = ref.read(filesRepoProvider);
    Widget body;
    if (_imgExt.contains(x)) {
      body = _ImageBody(e);
    } else if (x == 'md' || x == 'markdown') {
      body = _AsyncTextBody(future: repo.fetchText(e.path), markdown: true);
    } else if (_textExt.contains(x)) {
      body = _AsyncTextBody(future: repo.fetchText(e.path));
    } else if (_officeExt.contains(x)) {
      body = _AsyncTextBody(future: repo.extractText(e.path));
    } else {
      _downloadSheet(e, '.$x 格式暂不支持预览');
      return;
    }
    showDialog(
      context: context,
      builder: (_) =>
          _PreviewDialog(entry: e, onDownload: () => _download(e), child: body),
    );
  }

  // 不可预览 / 文件太大 → 底部操作条:提示原因 + 下载入口。
  void _downloadSheet(FileEntry e, String hint) {
    showModalBottomSheet(
      context: context,
      shape: const RoundedRectangleBorder(
          borderRadius: BorderRadius.vertical(top: Radius.circular(20))),
      builder: (_) => SafeArea(
        child: Column(mainAxisSize: MainAxisSize.min, children: [
          const SizedBox(height: 16),
          Text(hint, style: const TextStyle(color: AppTheme.muted)),
          const SizedBox(height: 6),
          ListTile(
            leading: const Icon(Icons.download_rounded, color: AppTheme.teal),
            title: const Text('下载 / 分享'),
            onTap: () {
              Navigator.pop(context);
              _download(e);
            },
          ),
          const SizedBox(height: 8),
        ]),
      ),
    );
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
            icon: Icon(_showHidden
                ? Icons.visibility_rounded
                : Icons.visibility_off_rounded),
            tooltip: _showHidden ? '隐藏「.」开头文件' : '显示隐藏文件',
            onPressed: () => setState(() => _showHidden = !_showHidden),
          ),
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
          var items = [...list];
          if (!_showHidden) {
            items = items.where((e) => !e.name.startsWith('.')).toList();
          }
          items.sort((a, b) {
            if (a.isDir != b.isDir) return a.isDir ? -1 : 1;
            return a.name.toLowerCase().compareTo(b.name.toLowerCase());
          });
          return RefreshIndicator(
            onRefresh: () async => _refresh(),
            child: items.isEmpty
                ? ListView(children: const [
                    SizedBox(height: 160),
                    Center(
                        child: Text('空目录',
                            style: TextStyle(color: AppTheme.muted))),
                  ])
                : ListView.builder(
                    padding: const EdgeInsets.fromLTRB(12, 10, 12, 24),
                    itemCount: items.length,
                    itemBuilder: (_, i) => _row(items[i]),
                  ),
          );
        },
      ),
    );
  }

  Widget _row(FileEntry e) {
    final (icon, color) = _typeStyle(e);
    return Padding(
      padding: const EdgeInsets.only(bottom: 8),
      child: Dismissible(
        key: ValueKey(e.path),
        direction: DismissDirection.endToStart,
        background: Container(
          alignment: Alignment.centerRight,
          padding: const EdgeInsets.only(right: 20),
          decoration: BoxDecoration(
              color: AppTheme.dangerSoft,
              borderRadius: BorderRadius.circular(AppTheme.rCard)),
          child: const Icon(Icons.delete_outline, color: AppTheme.danger),
        ),
        confirmDismiss: (_) => _confirmDelete(e),
        child: Container(
          decoration: BoxDecoration(
            color: AppTheme.surface,
            borderRadius: BorderRadius.circular(AppTheme.rCard),
            border: Border.all(color: AppTheme.border),
          ),
          child: Material(
            color: Colors.transparent,
            child: InkWell(
              borderRadius: BorderRadius.circular(AppTheme.rCard),
              onTap: () => _open(e),
              child: Padding(
                padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 11),
                child: Row(children: [
                  Container(
                    width: 40,
                    height: 40,
                    decoration: BoxDecoration(
                        color: color.withValues(alpha: 0.12),
                        borderRadius: BorderRadius.circular(11)),
                    child: Icon(icon, color: color, size: 22),
                  ),
                  const SizedBox(width: 12),
                  Expanded(
                    child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text(e.name,
                              maxLines: 1,
                              overflow: TextOverflow.ellipsis,
                              style: const TextStyle(
                                  fontSize: 14.5,
                                  fontWeight: FontWeight.w500,
                                  color: AppTheme.ink)),
                          if (!e.isDir) ...[
                            const SizedBox(height: 2),
                            Text(e.prettySize,
                                style: const TextStyle(
                                    fontSize: 12, color: AppTheme.faint)),
                          ],
                        ]),
                  ),
                  const SizedBox(width: 8),
                  if (e.isDir)
                    const Icon(Icons.chevron_right_rounded,
                        color: AppTheme.faint)
                  else if (_downloading.contains(e.path))
                    const Padding(
                      padding: EdgeInsets.all(12),
                      child: SizedBox(
                          width: 18,
                          height: 18,
                          child: CircularProgressIndicator(strokeWidth: 2)),
                    )
                  else
                    IconButton(
                      icon: const Icon(Icons.download_rounded,
                          size: 20, color: AppTheme.muted),
                      tooltip: '下载',
                      onPressed: () => _download(e),
                    ),
                ]),
              ),
            ),
          ),
        ),
      ),
    );
  }
}

/// 统一预览弹窗:顶栏(文件名 + 下载 + 关闭)+ 内容区(定高 75%,内容自滚动)。
class _PreviewDialog extends StatelessWidget {
  final FileEntry entry;
  final VoidCallback onDownload;
  final Widget child;
  const _PreviewDialog(
      {required this.entry, required this.onDownload, required this.child});
  @override
  Widget build(BuildContext context) {
    return Dialog(
      insetPadding: const EdgeInsets.all(16),
      child: SizedBox(
        height: MediaQuery.of(context).size.height * 0.75,
        child: Column(children: [
          Row(children: [
            const SizedBox(width: 16),
            Expanded(
              child: Text(entry.name,
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: const TextStyle(
                      fontSize: 15, fontWeight: FontWeight.w600)),
            ),
            IconButton(
                icon: const Icon(Icons.download_rounded),
                tooltip: '下载',
                onPressed: onDownload),
            IconButton(
                icon: const Icon(Icons.close),
                onPressed: () => Navigator.pop(context)),
          ]),
          const Divider(height: 1),
          Expanded(child: child),
        ]),
      ),
    );
  }
}

/// 图片预览(带 token 取字节 + 可缩放)。
class _ImageBody extends ConsumerWidget {
  final FileEntry entry;
  const _ImageBody(this.entry);
  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final img = ref.watch(sentImageProvider(entry.path));
    return img.when(
      loading: () => const Center(child: CircularProgressIndicator()),
      error: (e, _) => Padding(
          padding: const EdgeInsets.all(24), child: Text('加载失败: $e')),
      data: (bytes) =>
          Center(child: InteractiveViewer(child: Image.memory(bytes))),
    );
  }
}

/// 文本/代码/markdown/抽取文本统一异步内容。
class _AsyncTextBody extends StatelessWidget {
  final Future<String> future;
  final bool markdown;
  const _AsyncTextBody({required this.future, this.markdown = false});
  @override
  Widget build(BuildContext context) {
    return FutureBuilder<String>(
      future: future,
      builder: (_, snap) {
        if (snap.connectionState != ConnectionState.done) {
          return const Center(child: CircularProgressIndicator());
        }
        if (snap.hasError) {
          return Padding(
              padding: const EdgeInsets.all(24),
              child: Text('预览失败: ${snap.error}'));
        }
        final text = snap.data ?? '';
        if (text.isEmpty) {
          return const Center(
              child: Text('(空文件)', style: TextStyle(color: AppTheme.muted)));
        }
        if (markdown) {
          return Markdown(data: text, padding: const EdgeInsets.all(16));
        }
        return SingleChildScrollView(
          padding: const EdgeInsets.all(14),
          child: SelectableText(
            text,
            style: const TextStyle(
                fontSize: 12.5,
                height: 1.5,
                fontFamily: 'monospace',
                color: AppTheme.ink),
          ),
        );
      },
    );
  }
}
