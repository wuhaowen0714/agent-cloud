import 'package:dio/dio.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:image_picker/image_picker.dart';
import '../auth/auth_controller.dart'; // dioProvider

/// 工作区文件上传(多模态发图)。图片落到工作区 uploads/,
/// 返回相对路径列表 —— 即 turn 的 images 字段(后端按工作区相对路径读图)。
class FilesRepository {
  FilesRepository(this._dio);
  final Dio _dio;

  Future<List<String>> uploadImages(List<XFile> images) async {
    final form = FormData();
    for (var i = 0; i < images.length; i++) {
      final img = images[i];
      // 加时间戳前缀避免同名覆盖(后端 write 原子替换会盖掉历史同名图)。
      final stamp = DateTime.now().microsecondsSinceEpoch;
      form.files.add(MapEntry(
        'files',
        MultipartFile.fromBytes(await img.readAsBytes(),
            filename: '${stamp}_${i}_${img.name}'),
      ));
    }
    final r = await _dio.post('/files/upload',
        queryParameters: {'path': 'uploads'}, data: form);
    return (r.data as List)
        .map((e) => (e as Map<String, dynamic>)['path'] as String)
        .toList();
  }
}

final filesRepoProvider =
    Provider<FilesRepository>((ref) => FilesRepository(ref.read(dioProvider)));
