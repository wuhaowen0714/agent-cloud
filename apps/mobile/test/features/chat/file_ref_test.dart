import 'package:flutter_test/flutter_test.dart';
import 'package:agent_cloud_mobile/features/chat/file_ref.dart';

void main() {
  group('atTokenAt', () {
    test('句首 @ 触发', () {
      expect(atTokenAt('@', 1), const AtToken(0, ''));
      expect(atTokenAt('@src', 4), const AtToken(0, 'src'));
    });
    test('空白后 @ 触发(空格/换行)', () {
      expect(atTokenAt('看下 @app', 7), const AtToken(3, 'app'));
      expect(atTokenAt('hi\n@x', 5), const AtToken(3, 'x'));
    });
    test('邮箱(@ 前非空白)不触发', () {
      expect(atTokenAt('mail me a@b.com', 15), isNull);
    });
    test('光标在词中间只取 @ 到光标', () {
      expect(atTokenAt('@abcd', 3), const AtToken(0, 'ab'));
    });
    test('光标在 @ 之前(词外)不触发', () {
      expect(atTokenAt('@x', 0), isNull);
    });
    test('无 @ / 词内第二个 @ → null', () {
      expect(atTokenAt('hello', 5), isNull);
      expect(atTokenAt('@a@b', 4), isNull);
    });
    test('中文 query', () {
      expect(atTokenAt('@小说', 3), const AtToken(0, '小说'));
    });
    test('@ 词已结束(光标在后续词上)不触发', () {
      expect(atTokenAt('@src/a.py 然后', 12), isNull);
    });
  });

  group('filterPaths', () {
    const paths = ['src/App.tsx', 'src/main.tsx', 'docs/读我.md', 'README.md'];
    test('大小写不敏感子串(路径任意位置)', () {
      expect(filterPaths(paths, 'app'), ['src/App.tsx']);
      expect(filterPaths(paths, 'READ'), ['README.md']);
    });
    test('中文命中', () {
      expect(filterPaths(paths, '读我'), ['docs/读我.md']);
    });
    test('空 query 全量保序', () {
      expect(filterPaths(paths, ''), paths);
    });
    test('max 截断', () {
      final many = List.generate(30, (i) => 'f$i.txt');
      expect(filterPaths(many, '', max: 3), ['f0.txt', 'f1.txt', 'f2.txt']);
      expect(filterPaths(many, '').length, 20);
    });
    test('无命中 → 空表', () {
      expect(filterPaths(paths, 'zzz'), isEmpty);
    });
  });
}
