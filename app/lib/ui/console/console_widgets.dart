/// Building blocks of the controller layout: pad-aware rows, the stepper row
/// (left/right change the value), and PadListener.
library;

import 'dart:async';

import 'package:flutter/material.dart';

import '../../app/pad_input.dart';
import '../brutal/brutal.dart';

/// Calls [onAction] for bus actions while this route is on top.
class PadListener extends StatefulWidget {
  const PadListener({super.key, required this.onAction, required this.child});
  final void Function(PadAction a) onAction;
  final Widget child;

  @override
  State<PadListener> createState() => _PadListenerState();
}

class _PadListenerState extends State<PadListener> {
  StreamSubscription<PadAction>? _sub;

  @override
  void initState() {
    super.initState();
    _sub = PadBus.stream.listen((a) {
      if (!mounted) return;
      final route = ModalRoute.of(context);
      if (route != null && !route.isCurrent) return;
      widget.onAction(a);
    });
  }

  @override
  void dispose() {
    _sub?.cancel();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => widget.child;
}

/// A full-width console row: `LABEL ......... < VALUE >`. A runs [onPressed];
/// left/right step through values via [onStep].
class ConsoleRow extends StatefulWidget {
  const ConsoleRow({
    super.key,
    required this.label,
    this.value,
    this.onPressed,
    this.onStep,
    this.icon,
    this.primary = false,
    this.danger = false,
    this.autofocus = false,
    this.focusNode,
    this.sub,
  });

  final String label;
  final String? value;
  final VoidCallback? onPressed;
  final void Function(int dir)? onStep;
  final PixelGlyph? icon;
  final bool primary, danger, autofocus;
  final FocusNode? focusNode;
  final String? sub;

  @override
  State<ConsoleRow> createState() => _ConsoleRowState();
}

class _ConsoleRowState extends State<ConsoleRow> {
  final Object _owner = Object();

  @override
  void dispose() {
    PadSide.release(_owner);
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final t = context.brutal;
    final w = widget;
    return Pressable(
      autofocus: w.autofocus,
      focusNode: w.focusNode,
      onPressed: w.onPressed ?? (w.onStep == null ? null : () => w.onStep!(1)),
      onFocusChange: (f) {
        if (f && w.onStep != null) {
          PadSide.claim(_owner, (d) => w.onStep!(d));
        } else {
          PadSide.release(_owner);
        }
      },
      builder: (c, st) {
        var fill = w.primary ? t.primary : t.panel;
        var fg = w.primary ? t.onPrimary : (w.danger ? t.danger : t.ink);
        if (st.active) {
          fill = t.focus;
          fg = t.onFocus;
        }
        if (!st.enabled) {
          fill = t.muted;
          fg = t.mutedText;
        }
        final down = st.pressed;
        return Padding(
          padding: EdgeInsets.only(
            right: t.shadowOffset.dx,
            bottom: t.shadowOffset.dy,
          ),
          child: Transform.translate(
            offset: down ? t.shadowOffset : Offset.zero,
            child: Container(
              height: t.buttonHeight + 8 * t.scale,
              padding: EdgeInsets.symmetric(horizontal: t.s4),
              decoration: BoxDecoration(
                color: fill,
                border: Border.all(color: t.ink, width: t.border),
                boxShadow: [
                  BoxShadow(
                    color: t.shadow,
                    offset: down ? Offset.zero : t.shadowOffset,
                  ),
                ],
              ),
              child: Row(
                children: [
                  if (w.icon != null) ...[
                    PixelIcon(w.icon!, color: fg, size: t.iconSize * 1.5),
                    SizedBox(width: t.s3),
                  ],
                  Expanded(
                    child: Column(
                      mainAxisAlignment: MainAxisAlignment.center,
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(
                          w.label.toUpperCase(),
                          style: t.title.copyWith(color: fg),
                        ),
                        if (w.sub != null)
                          Text(
                            w.sub!,
                            style: t.small.copyWith(color: fg.withAlpha(190)),
                            overflow: TextOverflow.ellipsis,
                          ),
                      ],
                    ),
                  ),
                  if (w.value != null)
                    Text(
                      w.onStep != null && st.active
                          ? '<  ${w.value!.toUpperCase()}  >'
                          : w.value!.toUpperCase(),
                      style: t.title.copyWith(color: fg),
                    ),
                  if (st.active && t.console)
                    Text('  <-', style: t.label.copyWith(color: fg)),
                ],
              ),
            ),
          ),
        );
      },
    );
  }
}

/// Black bar at the top with the wordmark and the page tabs.
class ConsoleHeader extends StatelessWidget {
  const ConsoleHeader({
    super.key,
    required this.pages,
    required this.index,
    required this.right,
  });
  final List<String> pages;
  final int index;
  final String right;

  @override
  Widget build(BuildContext context) {
    final t = context.brutal;
    return Container(
      color: t.headerBar,
      padding: EdgeInsets.symmetric(horizontal: t.s6, vertical: t.s3),
      child: Row(
        children: [
          Container(
            color: t.focus,
            padding: EdgeInsets.symmetric(horizontal: t.s3, vertical: t.s1),
            child: Text(
              'HELIXSR/',
              style: t.displaySmall.copyWith(color: t.onFocus),
            ),
          ),
          SizedBox(width: t.s6),
          const KeyGlyph('LB'),
          SizedBox(width: t.s3),
          for (var i = 0; i < pages.length; i++) ...[
            Container(
              color: i == index ? t.focus : Colors.transparent,
              padding: EdgeInsets.symmetric(horizontal: t.s3, vertical: t.s1),
              child: Text(
                pages[i].toUpperCase(),
                style: t.title.copyWith(
                  color: i == index ? t.onFocus : t.onHeaderBar,
                ),
              ),
            ),
            SizedBox(width: t.s2),
          ],
          SizedBox(width: t.s1),
          const KeyGlyph('RB'),
          const Spacer(),
          Text(right, style: t.label.copyWith(color: t.onHeaderBar)),
        ],
      ),
    );
  }
}
