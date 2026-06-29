import 'dart:convert';
import 'dart:typed_data';
import 'package:dio/dio.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:file_selector/file_selector.dart'; // XFile
import '../auth/auth_controller.dart'; // dioProvider
import '../../models/file_entry.dart';

/// 工作区文件:上传 / 列目录 / 新建 / 删除 / 抽取文本 / 取字节。
class FilesRepository {
  FilesRepository(this._dio);
  final Dio _dio;

  /// 上传任意文件到工作区(默认 uploads/,文件管理可指定目录),返回相对路径。
  /// 优先 fromFile(走文件流、不全进内存,大文件不 OOM);无路径时回退 bytes。
  Future<List<String>> uploadFiles(List<XFile> files,
      {String dir = 'uploads'}) async {
    final form = FormData();
    for (var i = 0; i < files.length; i++) {
      final f = files[i];
      // 加时间戳前缀避免同名覆盖。
      final stamp = DateTime.now().microsecondsSinceEpoch;
      form.files.add(MapEntry(
        'files',
        await MultipartFile.fromFile(f.path,
            filename: '${stamp}_${i}_${f.name}'),
      ));
    }
    final r = await _dio.post('/files/upload',
        queryParameters: {'path': dir}, data: form);
    return (r.data as List)
        .map((e) => (e as Map<String, dynamic>)['path'] as String)
        .toList();
  }

  /// 列目录(根为空字符串)。
  Future<List<FileEntry>> list(String path) async {
    final r = await _dio.get('/files', queryParameters: {'path': path});
    return (r.data as List)
        .map((e) => FileEntry.fromJson(e as Map<String, dynamic>))
        .toList();
  }

  /// 递归列工作区全部文件的相对路径(仅文件;后端 store.walk 剪掉点目录/node_modules 等)。
  /// 供 @ 文件引用补全 —— 与单层目录列表 list() 不同。
  Future<List<String>> indexFiles() async {
    final r = await _dio.get('/files/index');
    return (r.data as List).cast<String>();
  }

  Future<void> mkdir(String path) =>
      _dio.post('/files/mkdir', data: {'path': path});

  Future<void> delete(String path) =>
      _dio.delete('/files', queryParameters: {'path': path});

  /// 文档(pdf/docx/...)抽取文本预览。
  Future<String> extractText(String path) async {
    final r = await _dio.get('/files/extract', queryParameters: {'path': path});
    return (r.data as Map<String, dynamic>)['text'] as String? ?? '';
  }

  /// 取工作区文件原始字节(图片预览 / 下载 / 文本预览;/files/raw 带 token,不能直接 <img>)。
  Future<Uint8List> fetchBytes(String path) async {
    final r = await _dio.get<List<int>>(
      '/files/raw',
      queryParameters: {'path': path},
      options: Options(responseType: ResponseType.bytes),
    );
    return Uint8List.fromList(r.data!);
  }

  /// 取文本类文件内容(代码/md/html/json…),UTF-8 解码(容错坏字节)。
  Future<String> fetchText(String path) async =>
      utf8.decode(await fetchBytes(path), allowMalformed: true);

  /// 流式下载到本地文件(dio.download 分块写盘,不全进内存 → 大文件不 OOM)。
  Future<void> downloadToFile(String path, String savePath) =>
      _dio.download('/files/raw', savePath,
          queryParameters: {'path': path, 'attachment': true});
}

final filesRepoProvider =
    Provider<FilesRepository>((ref) => FilesRepository(ref.read(dioProvider)));

/// 已发图缩略图字节,按 path 缓存(autoDispose 离开页面释放)。
final sentImageProvider = FutureProvider.autoDispose.family<Uint8List, String>(
    (ref, path) => ref.read(filesRepoProvider).fetchBytes(path));

/// 目录列表,按 path 缓存。
final filesListProvider =
    FutureProvider.autoDispose.family<List<FileEntry>, String>(
        (ref, path) => ref.read(filesRepoProvider).list(path));

/// @ 文件引用的工作区文件索引(递归全路径)。autoDispose:离开会话释放,下次进会话重拉。
final fileIndexProvider = FutureProvider.autoDispose<List<String>>(
    (ref) => ref.read(filesRepoProvider).indexFiles());
