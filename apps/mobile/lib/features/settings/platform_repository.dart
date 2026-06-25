import 'package:dio/dio.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../auth/auth_controller.dart'; // dioProvider

/// 平台模型清单(session 选 sophnet 时的 model 候选)。
class PlatformModels {
  final List<String> models;
  final String defaultModel;
  final List<String> visionModels; // 支持图片输入的子集

  const PlatformModels(this.models, this.defaultModel, this.visionModels);

  factory PlatformModels.fromJson(Map<String, dynamic> j) => PlatformModels(
        (j['models'] as List).cast<String>(),
        j['default'] as String,
        (j['vision_models'] as List).cast<String>(),
      );
}

class PlatformRepository {
  PlatformRepository(this._dio);
  final Dio _dio;

  Future<PlatformModels> getModels() async {
    final r = await _dio.get('/platform/models');
    return PlatformModels.fromJson(r.data as Map<String, dynamic>);
  }
}

final platformRepoProvider =
    Provider((ref) => PlatformRepository(ref.read(dioProvider)));

final platformModelsProvider = FutureProvider<PlatformModels>(
    (ref) => ref.read(platformRepoProvider).getModels());
