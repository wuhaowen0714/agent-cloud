import 'package:flutter/material.dart';

/// 对标 web 的浅色 + teal 主色。
class AppTheme {
  static const _seed = Color(0xFF0D9488); // teal-600

  static ThemeData light() => ThemeData(
        useMaterial3: true,
        colorScheme: ColorScheme.fromSeed(seedColor: _seed),
        scaffoldBackgroundColor: const Color(0xFFF8FAFC), // slate-50
      );
}
