import 'package:flutter/material.dart';
import 'brand_logo.dart';

/// bootstrap(探登录态)期间的启动页。
/// 存在意义:不让 home 在 auth 未就绪时 build —— 否则 home 会在登录前发出
/// 无 token 的 GET /sessions → 401(新装首登 401 的真因)。
class SplashPage extends StatelessWidget {
  const SplashPage({super.key});
  @override
  Widget build(BuildContext context) => const Scaffold(
        body: Center(
          child: Column(mainAxisSize: MainAxisSize.min, children: [
            BrandLogo(size: 72),
            SizedBox(height: 28),
            SizedBox(
                width: 22,
                height: 22,
                child: CircularProgressIndicator(strokeWidth: 2.4)),
          ]),
        ),
      );
}
