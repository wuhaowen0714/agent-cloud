/// 会话列表时间分组:按本地日历日距今天数分档(对标 web timeGroupLabel)。
/// 未来(时钟偏差)归今天;null/坏值归更早。
String timeGroupLabel(DateTime? d) {
  if (d == null) return '更早';
  final now = DateTime.now();
  DateTime startOf(DateTime x) => DateTime(x.year, x.month, x.day);
  final days = startOf(now).difference(startOf(d.toLocal())).inDays;
  if (days <= 0) return '今天';
  if (days == 1) return '昨天';
  if (days <= 7) return '前 7 天';
  if (days <= 30) return '前 30 天';
  return '更早';
}
