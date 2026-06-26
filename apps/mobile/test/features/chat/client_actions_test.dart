import 'package:flutter_test/flutter_test.dart';
import 'package:agent_cloud_mobile/features/chat/client_actions.dart';

void main() {
  test('start_navigation 在客户端动作工具集里', () {
    expect(kClientActionTools.contains('start_navigation'), isTrue);
  });

  test('驾车:高德优先,顺序 高德→百度→geo,URI 正确', () {
    final c = navCandidates('北京南站', 'driving');
    expect(c.length, 3);
    expect(c[0].package, 'com.autonavi.minimap');
    expect(c[0].data, contains('androidamap://keywordNavi'));
    expect(c[0].data, contains('keyword=${Uri.encodeComponent('北京南站')}'));
    expect(c[1].package, 'com.baidu.BaiduMap');
    expect(c[1].data, contains('baidumap://map/direction'));
    expect(c[1].data, contains('mode=driving'));
    expect(c[2].package, isNull); // geo 兜底无 package
    expect(c[2].data, startsWith('geo:0,0?q='));
  });

  test('步行:百度优先(高德 keywordNavi 仅驾车),mode 透传', () {
    final c = navCandidates('人民广场', 'walking');
    expect(c[0].package, 'com.baidu.BaiduMap');
    expect(c[0].data, contains('mode=walking'));
    expect(c[1].package, 'com.autonavi.minimap');
    expect(c.last.package, isNull); // 末位仍是 geo 兜底
  });

  test('目的地做 URL 编码(中文/空格不破坏 URI)', () {
    final c = navCandidates('三里屯 SOHO', 'driving');
    final enc = Uri.encodeComponent('三里屯 SOHO');
    expect(c[0].data, contains('keyword=$enc'));
    expect(c[0].data, isNot(contains('三里屯 SOHO'))); // 原文不应裸露在 URI 里
  });

  test('未知 mode 回退 driving(不构造非法 baidu mode)', () {
    final c = navCandidates('某地', 'fly');
    expect(c[0].package, 'com.autonavi.minimap'); // 非步行/公交/骑行 → 默认分支(高德优先)
    final baidu = c.firstWhere((x) => x.package == 'com.baidu.BaiduMap');
    expect(baidu.data, contains('mode=driving'));
  });
}
