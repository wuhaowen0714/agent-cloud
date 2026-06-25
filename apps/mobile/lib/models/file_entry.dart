/// 工作区文件/目录条目。
class FileEntry {
  final String name;
  final String path; // 工作区相对路径
  final bool isDir;
  final int size;

  const FileEntry({
    required this.name,
    required this.path,
    required this.isDir,
    required this.size,
  });

  factory FileEntry.fromJson(Map<String, dynamic> j) => FileEntry(
        name: j['name'] as String,
        path: j['path'] as String,
        isDir: j['is_dir'] as bool? ?? false,
        size: (j['size'] as num?)?.toInt() ?? 0,
      );

  /// 人类可读大小。
  String get prettySize {
    if (isDir) return '';
    if (size < 1024) return '$size B';
    if (size < 1024 * 1024) return '${(size / 1024).toStringAsFixed(0)} KB';
    return '${(size / 1024 / 1024).toStringAsFixed(1)} MB';
  }
}
