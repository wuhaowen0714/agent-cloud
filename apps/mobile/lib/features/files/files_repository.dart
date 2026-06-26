import 'dart:convert';
import 'dart:typed_data';
import 'package:dio/dio.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:image_picker/image_picker.dart';
import '../auth/auth_controller.dart'; // dioProvider
import '../../models/file_entry.dart';

/// 工作区文件:上传 / 列目录 / 新建 / 删除 / 抽取文本 / 取字节。
class FilesRepository {
  FilesRepository(this._dio);
  final Dio _dio;

  /// 上传图片到工作区(默认 uploads/,文件管理可指定目录),返回相对路径。
  Future<List<String>> uploadImages(List<XFile> images,
      {String dir = 'uploads'}) async {
    final form = FormData();
    for (var i = 0; i < images.length; i++) {
      final img = images[i];
      // 加时间戳前缀避免同名覆盖。
      final stamp = DateTime.now().microsecondsSinceEpoch;
      form.files.add(MapEntry(
        'files',
        MultipartFile.fromBytes(await img.readAsBytes(),
            filename: '${stamp}_${i}_${img.name}'),
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
