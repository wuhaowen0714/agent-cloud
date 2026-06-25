import 'dart:math' as math;
import 'package:flutter/material.dart';
import '../theme/app_theme.dart';

/// 品牌 logo:teal 渐变圆角方 + 白色四角火花(矢量,任意尺寸清晰)。
/// 与 launcher 图标(tool/gen_icon.py)同一造型。
class BrandLogo extends StatelessWidget {
  final double size;
  const BrandLogo({super.key, this.size = 64});

  @override
  Widget build(BuildContext context) => Container(
        width: size,
        height: size,
        decoration: BoxDecoration(
          gradient: const LinearGradient(
            begin: Alignment.topLeft,
            end: Alignment.bottomRight,
            colors: [Color(0xFF2DD4BF), Color(0xFF0D9488)],
          ),
          borderRadius: BorderRadius.circular(size * 0.28),
          boxShadow: [
            BoxShadow(
                color: AppTheme.teal.withValues(alpha: 0.32),
                blurRadius: size * 0.28,
                offset: Offset(0, size * 0.11)),
          ],
        ),
        child: CustomPaint(size: Size(size, size), painter: _SparkPainter()),
      );
}

class _SparkPainter extends CustomPainter {
  @override
  void paint(Canvas canvas, Size size) {
    final cx = size.width / 2, cy = size.height / 2;
    final tip = size.width * 0.30;
    final valley = tip * 0.36;
    final path = Path();
    for (var i = 0; i < 8; i++) {
      final ang = (90 - i * 45) * math.pi / 180;
      final r = i.isEven ? tip : valley;
      final x = cx + r * math.cos(ang);
      final y = cy - r * math.sin(ang);
      i == 0 ? path.moveTo(x, y) : path.lineTo(x, y);
    }
    path.close();
    canvas.drawPath(path, Paint()..color = Colors.white);
  }

  @override
  bool shouldRepaint(covariant CustomPainter oldDelegate) => false;
}
