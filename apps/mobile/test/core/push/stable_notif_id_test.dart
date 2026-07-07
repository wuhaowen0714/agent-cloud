import 'package:flutter_test/flutter_test.dart';
import 'package:agent_cloud_mobile/core/push/push_service.dart';

void main() {
  test('stableNotifId:同 id 恒同值(跨进程幂等的前提),uuid 前 8 hex 派生', () {
    const nid = '550e8400-e29b-41d4-a716-446655440000';
    expect(stableNotifId(nid), stableNotifId(nid));
    expect(stableNotifId(nid), 0x550e8400 & 0x7fffffff); // 确定性:不依赖 hashCode 随机种子
    expect(stableNotifId(nid), isNot(stableNotifId('660e8400-e29b-41d4-a716-446655440000')));
    expect(stableNotifId(nid) >= 0, isTrue);
  });

  test('stableNotifId:非 uuid 形状兜底且稳定', () {
    expect(stableNotifId('abc'), stableNotifId('abc'));
    expect(stableNotifId('abc') >= 0, isTrue);
  });
}
