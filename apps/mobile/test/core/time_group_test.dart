import 'package:flutter_test/flutter_test.dart';
import 'package:agent_cloud_mobile/core/util/time_group.dart';

void main() {
  test('timeGroupLabel 按日历日分档', () {
    expect(timeGroupLabel(null), '更早');
    expect(timeGroupLabel(DateTime.now()), '今天');
    expect(
        timeGroupLabel(DateTime.now().subtract(const Duration(days: 10))),
        '前 30 天');
    expect(
        timeGroupLabel(DateTime.now().subtract(const Duration(days: 40))),
        '更早');
  });
}
