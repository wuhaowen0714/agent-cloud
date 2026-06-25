import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'auth_controller.dart';

class LoginPage extends ConsumerStatefulWidget {
  const LoginPage({super.key});
  @override
  ConsumerState<LoginPage> createState() => _LoginPageState();
}

class _LoginPageState extends ConsumerState<LoginPage> {
  final _email = TextEditingController();
  final _pw = TextEditingController();
  bool _register = false;

  @override
  void dispose() {
    _email.dispose();
    _pw.dispose();
    super.dispose();
  }

  Future<void> _submit() async {
    final c = ref.read(authControllerProvider.notifier);
    if (_register) {
      await c.register(_email.text.trim(), _pw.text);
    } else {
      await c.login(_email.text.trim(), _pw.text);
    }
  }

  @override
  Widget build(BuildContext context) {
    final auth = ref.watch(authControllerProvider);
    final busy = auth.isLoading;
    return Scaffold(
      body: Center(
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 360),
          child: Padding(
            padding: const EdgeInsets.all(24),
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                Text(_register ? '注册' : '登录',
                    style: Theme.of(context).textTheme.headlineSmall),
                const SizedBox(height: 24),
                TextField(
                    controller: _email,
                    decoration: const InputDecoration(labelText: '邮箱'),
                    keyboardType: TextInputType.emailAddress),
                const SizedBox(height: 12),
                TextField(
                    controller: _pw,
                    obscureText: true,
                    decoration: const InputDecoration(labelText: '密码')),
                if (auth.hasError) ...[
                  const SizedBox(height: 12),
                  const Text('邮箱或密码错误', style: TextStyle(color: Colors.red)),
                ],
                const SizedBox(height: 24),
                FilledButton(
                    onPressed: busy ? null : _submit,
                    child: Text(busy ? '...' : (_register ? '注册' : '登录'))),
                TextButton(
                    onPressed: () => setState(() => _register = !_register),
                    child: Text(_register ? '已有账号?去登录' : '没有账号?去注册')),
              ],
            ),
          ),
        ),
      ),
    );
  }
}
