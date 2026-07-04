import 'package:flutter/material.dart';
import '../../core/theme/app_theme.dart';

/// edit 工具的红绿 diff 渲染(对标 web EditDiff):edit 是「精确替换」,直接呈现被换走
/// (红 -)/换来(绿 +)的文本就是最诚实的 diff,不做行内 LCS。
typedef EditPair = ({String oldText, String newText});

/// tool_call arguments → edits(不可信模型输出,逐项容错;非法项丢弃)。
List<EditPair> parseEdits(Map<String, dynamic> args) {
  final raw = args['edits'];
  if (raw is! List) return const [];
  final out = <EditPair>[];
  for (final e in raw) {
    if (e is! Map) continue;
    final o = e['old_text'];
    final n = e['new_text'];
    if (o is! String || n is! String) continue;
    out.add((oldText: o, newText: n));
  }
  return out;
}

const _red = Color(0xFFFEF2F2); // red-50
const _redInk = Color(0xFFB91C1C); // red-700
const _green = Color(0xFFECFDF5); // emerald-50
const _greenInk = Color(0xFF047857); // emerald-700

class EditDiffView extends StatelessWidget {
  final List<EditPair> edits;
  const EditDiffView(this.edits, {super.key});

  @override
  Widget build(BuildContext context) {
    if (edits.isEmpty) return const SizedBox.shrink();
    return Container(
      width: double.infinity,
      constraints: const BoxConstraints(maxHeight: 260),
      decoration: BoxDecoration(
          color: AppTheme.bg, borderRadius: BorderRadius.circular(8)),
      child: SingleChildScrollView(
        padding: const EdgeInsets.all(8),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            for (var i = 0; i < edits.length; i++) ...[
              if (i > 0)
                const Divider(height: 12, color: AppTheme.border),
              _lines('- ', edits[i].oldText, _red, _redInk),
              _lines('+ ', edits[i].newText, _green, _greenInk),
            ],
          ],
        ),
      ),
    );
  }

  Widget _lines(String prefix, String text, Color bg, Color ink) => Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          for (final line in text.split('\n'))
            Container(
              width: double.infinity,
              color: bg,
              child: Text('$prefix$line',
                  style: TextStyle(
                      fontSize: 12,
                      fontFamily: 'monospace',
                      height: 1.45,
                      color: ink)),
            ),
        ],
      );
}
