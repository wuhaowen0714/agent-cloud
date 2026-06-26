import 'package:flutter/material.dart';

/// 设计系统:teal 主色 + slate 中性阶,对标 web(浅色)。
/// 颜色/圆角集中定义为 token,各页面统一引用,避免散落的 Colors.xxx。
class AppTheme {
  // ── 主色 ──
  static const teal = Color(0xFF0D9488); // teal-600
  static const tealDark = Color(0xFF0F766E); // teal-700
  static const tealSoft = Color(0xFFF0FDFA); // teal-50 浅背景

  // ── 中性(slate)──
  static const bg = Color(0xFFF8FAFC); // slate-50 页面底
  static const surface = Colors.white; // 卡片/表面
  static const border = Color(0xFFE2E8F0); // slate-200 描边
  static const borderSoft = Color(0xFFF1F5F9); // slate-100 极淡分隔
  static const ink = Color(0xFF0F172A); // slate-900 主文字
  static const muted = Color(0xFF64748B); // slate-500 次要文字
  static const faint = Color(0xFF94A3B8); // slate-400 更淡
  static const danger = Color(0xFFE11D48); // rose-600
  static const dangerSoft = Color(0xFFFFF1F2); // rose-50

  // ── 圆角 ──
  static const rCard = 16.0;
  static const rField = 12.0;
  static const rChip = 8.0;

  static ThemeData light() {
    final scheme = ColorScheme.fromSeed(
      seedColor: teal,
      brightness: Brightness.light,
    ).copyWith(
      primary: teal,
      surface: surface,
      surfaceTint: Colors.transparent, // 去掉 M3 表面染色(默认会让卡片/AppBar 泛紫)
      onSurface: ink,
      outlineVariant: border,
    );

    return ThemeData(
      useMaterial3: true,
      colorScheme: scheme,
      scaffoldBackgroundColor: bg,
      appBarTheme: const AppBarTheme(
        backgroundColor: surface,
        surfaceTintColor: Colors.transparent,
        foregroundColor: ink,
        elevation: 0,
        scrolledUnderElevation: 0.5,
        centerTitle: false,
        titleTextStyle: TextStyle(
            color: ink, fontSize: 18, fontWeight: FontWeight.w600),
      ),
      cardTheme: CardThemeData(
        color: surface,
        elevation: 0,
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(rCard),
          side: const BorderSide(color: border),
        ),
        margin: EdgeInsets.zero,
      ),
      inputDecorationTheme: InputDecorationTheme(
        filled: true,
        fillColor: bg,
        contentPadding:
            const EdgeInsets.symmetric(horizontal: 14, vertical: 14),
        border: OutlineInputBorder(
          borderRadius: BorderRadius.circular(rField),
          borderSide: const BorderSide(color: border),
        ),
        enabledBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(rField),
          borderSide: const BorderSide(color: border),
        ),
        focusedBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(rField),
          borderSide: const BorderSide(color: teal, width: 1.6),
        ),
        hintStyle: const TextStyle(color: faint),
        labelStyle: const TextStyle(color: muted),
      ),
      filledButtonTheme: FilledButtonThemeData(
        style: FilledButton.styleFrom(
          backgroundColor: teal,
          foregroundColor: Colors.white,
          elevation: 0,
          padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 14),
          shape:
              RoundedRectangleBorder(borderRadius: BorderRadius.circular(rField)),
          textStyle: const TextStyle(fontSize: 15, fontWeight: FontWeight.w600),
        ),
      ),
      textButtonTheme: TextButtonThemeData(
        style: TextButton.styleFrom(foregroundColor: teal),
      ),
      listTileTheme: const ListTileThemeData(iconColor: muted),
      dividerTheme: const DividerThemeData(
        color: borderSoft,
        thickness: 1,
        space: 1,
      ),
      chipTheme: ChipThemeData(
        backgroundColor: tealSoft,
        side: BorderSide.none,
        labelStyle: const TextStyle(
            color: tealDark, fontSize: 12, fontWeight: FontWeight.w500),
        shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(rChip)),
        padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
      ),
      snackBarTheme: const SnackBarThemeData(behavior: SnackBarBehavior.floating),
      floatingActionButtonTheme: const FloatingActionButtonThemeData(
        backgroundColor: teal,
        foregroundColor: Colors.white,
      ),
    );
  }
}
