import 'package:flutter/material.dart';

import '../brutal/brutal.dart';

/// `KEY ............ CONTROL` settings row.
class CfgRow extends StatelessWidget {
  const CfgRow(this.label, {super.key, required this.control, this.hint});
  final String label;
  final Widget control;
  final String? hint;

  @override
  Widget build(BuildContext context) {
    final t = context.brutal;
    return Padding(
      padding: EdgeInsets.symmetric(vertical: t.s1 + 1),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.center,
        children: [
          ConstrainedBox(
            constraints: BoxConstraints(maxWidth: 200 * t.scale),
            child: Text(label.toUpperCase(), style: t.label),
          ),
          Expanded(
            child: Padding(
              padding: EdgeInsets.symmetric(horizontal: t.s2),
              child: LayoutBuilder(
                builder: (c, box) => Text(
                  List.filled(
                    (box.maxWidth / (7 * t.scale)).floor().clamp(0, 400),
                    '.',
                  ).join(),
                  maxLines: 1,
                  overflow: TextOverflow.clip,
                  style: t.small.copyWith(color: t.mutedText),
                ),
              ),
            ),
          ),
          Flexible(
            flex: 3,
            child: Align(alignment: Alignment.centerRight, child: control),
          ),
        ],
      ),
    );
  }
}

/// A settings section: header strip such as `APPEARANCE.CFG` + rows.
class CfgTable extends StatelessWidget {
  const CfgTable({
    super.key,
    required this.header,
    required this.rows,
    this.trailing,
  });
  final String header;
  final List<Widget> rows;
  final Widget? trailing;

  @override
  Widget build(BuildContext context) {
    final t = context.brutal;
    return Padding(
      padding: EdgeInsets.only(
        right: t.shadowOffset.dx,
        bottom: t.shadowOffset.dy,
      ),
      child: BrutalPanel(
        header: header,
        headerTrailing: trailing,
        child: Column(mainAxisSize: MainAxisSize.min, children: rows),
      ),
    );
  }
}

String modeLabel(String m) => m.toUpperCase();
