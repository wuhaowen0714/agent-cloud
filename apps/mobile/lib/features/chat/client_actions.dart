import 'package:android_intent_plus/android_intent.dart';

/// 客户端动作工具的 App 端执行(worker 只合成确认,真正的设备操作在此)。
/// chat_controller 收到 set_alarm / add_calendar_event 的 tool_call 后调本函数 → 系统 Intent。
/// 闹钟走 AlarmClock.ACTION_SET_ALARM,日历走 CalendarContract 的 ACTION_INSERT —— 都跳系统
/// 自带的闹钟 / 日历应用预填,用户确认即可,无需危险权限。
const kClientActionTools = {'set_alarm', 'add_calendar_event'};

Future<void> handleClientToolCall(String tool, Map<String, dynamic> args) async {
  try {
    switch (tool) {
      case 'set_alarm':
        await _setAlarm(args);
      case 'add_calendar_event':
        await _addCalendar(args);
    }
  } catch (_) {
    // 设备动作失败不影响对话(worker 已回合成确认);用户没看到系统界面会再开口
  }
}

Future<void> _setAlarm(Map<String, dynamic> args) async {
  final hour = (args['hour'] as num?)?.toInt();
  final minute = (args['minute'] as num?)?.toInt();
  if (hour == null || minute == null) return;
  final label = args['label'];
  final intent = AndroidIntent(
    action: 'android.intent.action.SET_ALARM', // AlarmClock.ACTION_SET_ALARM
    arguments: <String, dynamic>{
      'android.intent.extra.alarm.HOUR': hour,
      'android.intent.extra.alarm.MINUTES': minute,
      if (label is String && label.trim().isNotEmpty)
        'android.intent.extra.alarm.MESSAGE': label,
      // 不 SKIP_UI:跳系统闹钟界面让用户确认(更透明,且避免某些 ROM 静默设置无反馈)
      'android.intent.extra.alarm.SKIP_UI': false,
    },
  );
  await intent.launch();
}

Future<void> _addCalendar(Map<String, dynamic> args) async {
  final title = args['title'];
  final startStr = args['start'];
  if (title is! String || title.trim().isEmpty || startStr is! String) return;
  final start = DateTime.tryParse(startStr);
  if (start == null) return;
  final endStr = args['end'];
  final end = (endStr is String) ? DateTime.tryParse(endStr) : null;
  final location = args['location'];
  final description = args['description'];
  final intent = AndroidIntent(
    action: 'android.intent.action.INSERT', // CalendarContract ACTION_INSERT
    data: 'content://com.android.calendar/events',
    arguments: <String, dynamic>{
      'title': title,
      'beginTime': start.millisecondsSinceEpoch,
      'endTime':
          (end ?? start.add(const Duration(hours: 1))).millisecondsSinceEpoch,
      if (location is String && location.isNotEmpty) 'eventLocation': location,
      if (description is String && description.isNotEmpty)
        'description': description,
    },
  );
  await intent.launch();
}
