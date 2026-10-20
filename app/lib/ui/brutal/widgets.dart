/// The brutalist component kit used by both shells.
library;

import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../../app/pad_input.dart' show PadBus;
import 'pixel_icons.dart';
import 'pressable.dart';
import 'tokens.dart';

/// 8 px graph paper behind every screen.
class GridPaper8 extends StatelessWidget {
  const GridPaper8({super.key, this.child});
  final Widget? child;

  @override
  Widget build(BuildContext context) {
    final t = context.brutal;
    return ColoredBox(
      color: t.ground,
      child: CustomPaint(
        painter: _GridPainter(t.gridLine, t.gridLineMajor),
        child: child ?? const SizedBox.expand(),
      ),
    );
  }
}

class _GridPainter extends CustomPainter {
  _GridPainter(this.minor, this.major);
  final Color minor, major;

  @override
  void paint(Canvas canvas, Size size) {
    final pm = Paint()
      ..color = minor
      ..isAntiAlias = false;
    final pj = Paint()
      ..color = major
      ..isAntiAlias = false;
    var i = 0;
    for (double x = 0; x < size.width; x += 8, i++) {
      canvas.drawRect(
        Rect.fromLTWH(x, 0, 1, size.height),
        i % 4 == 0 ? pj : pm,
      );
    }
    i = 0;
    for (double y = 0; y < size.height; y += 8, i++) {
      canvas.drawRect(Rect.fromLTWH(0, y, size.width, 1), i % 4 == 0 ? pj : pm);
    }
  }

  @override
  bool shouldRepaint(_GridPainter old) =>
      old.minor != minor || old.major != major;
}

/// Box with a 3 px ink border and hard shadow; optional inverted header strip
/// (`VIDEO.CFG`).
class BrutalPanel extends StatelessWidget {
  const BrutalPanel({
    super.key,
    this.header,
    this.headerTrailing,
    this.fill,
    this.large = false,
    this.shadowed = true,
    this.padding,
    required this.child,
  });

  final String? header;
  final Widget? headerTrailing;
  final Color? fill;
  final bool large, shadowed;
  final EdgeInsetsGeometry? padding;
  final Widget child;

  @override
  Widget build(BuildContext context) {
    final t = context.brutal;
    return Container(
      decoration: t.panelDecoration(
        fill: fill,
        large: large,
        shadowed: shadowed,
      ),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          if (header != null)
            Container(
              color: t.headerBar,
              padding: EdgeInsets.symmetric(
                horizontal: t.s3,
                vertical: t.s1 + 2,
              ),
              child: Row(
                children: [
                  Expanded(
                    child: Text(
                      header!.toUpperCase(),
                      style: t.label.copyWith(color: t.onHeaderBar),
                      overflow: TextOverflow.ellipsis,
                    ),
                  ),
                  ?headerTrailing,
                ],
              ),
            ),
          Flexible(
            child: Padding(
              padding: padding ?? EdgeInsets.all(t.s3),
              child: child,
            ),
          ),
        ],
      ),
    );
  }
}

enum ButtonVariant { plain, primary, focus, dark, hazard }

/// Hard rectangle on a solid shadow. Pressing moves it onto the shadow.
/// Focused (or hovered) = hazard yellow with black text; on console a `<-`
/// marker points at it.
class BrutalButton extends StatelessWidget {
  const BrutalButton({
    super.key,
    required this.label,
    this.onPressed,
    this.variant = ButtonVariant.plain,
    this.icon,
    this.index,
    this.value,
    this.expand = false,
    this.autofocus = false,
    this.focusNode,
    this.selected = false,
  });

  final String label;
  final VoidCallback? onPressed;
  final ButtonVariant variant;
  final PixelGlyph? icon;
  final String? index;
  final String? value;
  final bool expand, autofocus, selected;
  final FocusNode? focusNode;

  @override
  Widget build(BuildContext context) {
    final t = context.brutal;
    return Pressable(
      onPressed: onPressed,
      autofocus: autofocus,
      focusNode: focusNode,
      semanticLabel: label,
      builder: (context, st) {
        Color fill, fg;
        switch (variant) {
          case ButtonVariant.primary:
            fill = t.primary;
            fg = t.onPrimary;
          case ButtonVariant.focus:
            fill = t.focus;
            fg = t.onFocus;
          case ButtonVariant.dark:
            fill = const Color(0xFF000000);
            fg = t.focus;
          case ButtonVariant.hazard:
            fill = t.panel;
            fg = t.danger;
          case ButtonVariant.plain:
            fill = t.panel;
            fg = t.ink;
        }
        var outline = t.ink;
        if (selected) {
          fill = t.focus;
          fg = t.onFocus;
        }
        if (st.active) {
          if (fill == t.focus) {
            outline = t.primary; // already yellow: blue outline instead
          } else {
            fill = t.focus;
            fg = t.onFocus;
          }
        }
        if (!st.enabled) {
          fill = t.muted;
          fg = t.mutedText;
        }
        final off = st.pressed || selected ? Offset.zero : t.shadowOffset;
        final shift = st.pressed || selected ? t.shadowOffset : Offset.zero;
        final content = Row(
          mainAxisSize: expand ? MainAxisSize.max : MainAxisSize.min,
          children: [
            if (index != null) ...[
              Text(index!, style: t.label.copyWith(color: fg.withAlpha(150))),
              SizedBox(width: t.s2),
            ],
            if (icon != null) ...[
              PixelIcon(icon!, color: fg, size: t.iconSize),
              SizedBox(width: t.s2),
            ],
            Flexible(
              child: Text(
                label.toUpperCase(),
                style: t.label.copyWith(color: fg),
                overflow: TextOverflow.ellipsis,
                maxLines: 1,
              ),
            ),
            if (expand) const Spacer(),
            if (value != null) ...[
              SizedBox(width: t.s3),
              Text(
                '[${value!.toUpperCase()}]',
                style: t.label.copyWith(color: fg),
              ),
            ],
          ],
        );
        final box = Transform.translate(
          offset: shift,
          child: Container(
            height: t.buttonHeight,
            padding: EdgeInsets.symmetric(horizontal: t.s3),
            alignment: Alignment.centerLeft,
            decoration: BoxDecoration(
              color: fill,
              border: Border.all(color: outline, width: t.border),
              boxShadow: [BoxShadow(color: t.shadow, offset: off)],
            ),
            child: content,
          ),
        );
        // The shadow lives outside the box: reserve room for it.
        final padded = Padding(
          padding: EdgeInsets.only(
            right: t.shadowOffset.dx,
            bottom: t.shadowOffset.dy,
          ),
          child: box,
        );
        if (t.console && st.active) {
          return Row(
            mainAxisSize: expand ? MainAxisSize.max : MainAxisSize.min,
            children: [
              expand ? Expanded(child: padded) : padded,
              Text(' <-', style: t.label.copyWith(color: t.ink)),
            ],
          );
        }
        return padded;
      },
    );
  }
}

/// `[ON]` / `[OFF]` two-state key.
class CfgToggle extends StatelessWidget {
  const CfgToggle({
    super.key,
    required this.value,
    this.onChanged,
    this.focusNode,
    this.autofocus = false,
  });
  final bool value;
  final ValueChanged<bool>? onChanged;
  final FocusNode? focusNode;
  final bool autofocus;

  @override
  Widget build(BuildContext context) {
    final t = context.brutal;
    return Pressable(
      focusNode: focusNode,
      autofocus: autofocus,
      onPressed: onChanged == null ? null : () => onChanged!(!value),
      semanticLabel: value ? 'ON' : 'OFF',
      builder: (c, st) {
        var fill = value ? const Color(0xFF000000) : t.panel;
        var fg = value ? const Color(0xFFFFFFFF) : t.ink;
        if (st.active) {
          fill = t.focus;
          fg = t.onFocus;
        }
        if (!st.enabled) {
          fill = t.muted;
          fg = t.mutedText;
        }
        return Container(
          width: 64 * t.scale,
          height: t.buttonHeight - 8 * t.scale,
          alignment: Alignment.center,
          decoration: BoxDecoration(
            color: fill,
            border: Border.all(color: t.ink, width: t.border),
          ),
          child: Text(
            value ? '[ON]' : '[OFF]',
            style: t.label.copyWith(color: fg),
          ),
        );
      },
    );
  }
}

/// `[1X] 2X 4X` segment choice; the chosen value is bracketed and yellow.
class CfgSegment<T> extends StatelessWidget {
  const CfgSegment({
    super.key,
    required this.options,
    required this.value,
    required this.labelOf,
    this.onChanged,
    this.wrap = true,
  });

  final List<T> options;
  final T value;
  final String Function(T) labelOf;
  final ValueChanged<T>? onChanged;
  final bool wrap;

  @override
  Widget build(BuildContext context) {
    final t = context.brutal;
    final items = [
      for (final o in options)
        Pressable(
          onPressed: onChanged == null ? null : () => onChanged!(o),
          builder: (c, st) {
            final sel = o == value;
            final hot = st.active;
            return Container(
              height: t.buttonHeight - 8 * t.scale,
              padding: EdgeInsets.symmetric(horizontal: t.s3),
              alignment: Alignment.center,
              decoration: BoxDecoration(
                color: sel || hot ? t.focus : t.panel,
                border: Border.all(
                  color: sel && hot ? t.primary : t.ink,
                  width: t.border,
                ),
              ),
              child: Text(
                sel
                    ? '[${labelOf(o).toUpperCase()}]'
                    : labelOf(o).toUpperCase(),
                style: t.label.copyWith(color: sel || hot ? t.onFocus : t.ink),
              ),
            );
          },
        ),
    ];
    return wrap
        ? Wrap(spacing: t.s2, runSpacing: t.s2, children: items)
        : Row(
            mainAxisSize: MainAxisSize.min,
            children: [
              for (final w in items)
                Padding(
                  padding: EdgeInsets.only(right: t.s2),
                  child: w,
                ),
            ],
          );
  }
}

/// Rotated yellow label: `PAUSED`, `NEW`, `ACTIVE`.
class Sticker extends StatelessWidget {
  const Sticker(
    this.text, {
    super.key,
    this.color,
    this.fg,
    this.angle = -0.07,
    this.display = false,
  });
  final String text;
  final Color? color, fg;
  final double angle;
  final bool display;

  @override
  Widget build(BuildContext context) {
    final t = context.brutal;
    return Transform.rotate(
      angle: angle,
      child: Container(
        padding: EdgeInsets.symmetric(horizontal: t.s2, vertical: t.s1),
        decoration: t.panelDecoration(fill: color ?? t.focus),
        child: Text(
          text.toUpperCase(),
          style: (display ? t.displaySmall : t.label).copyWith(
            color: fg ?? t.onFocus,
          ),
        ),
      ),
    );
  }
}

/// Small bordered tag (`DLSS`, `RE ENGINE`) without rotation or shadow.
class Tag extends StatelessWidget {
  const Tag(this.text, {super.key, this.fill, this.fg});
  final String text;
  final Color? fill, fg;

  @override
  Widget build(BuildContext context) {
    final t = context.brutal;
    return Container(
      padding: EdgeInsets.symmetric(horizontal: t.s1 + 2, vertical: 1),
      decoration: BoxDecoration(
        color: fill ?? t.panel,
        border: Border.all(color: t.ink, width: t.borderThin),
      ),
      child: Text(
        text.toUpperCase(),
        style: t.small.copyWith(
          color: fg ?? t.ink,
          fontWeight: FontWeight.w600,
        ),
      ),
    );
  }
}

/// A pad/keyboard hint glyph: bordered square with the key letter.
class KeyGlyph extends StatelessWidget {
  const KeyGlyph(this.keyLabel, {super.key, this.filled = false});
  final String keyLabel;
  final bool filled;

  @override
  Widget build(BuildContext context) {
    final t = context.brutal;
    final wide = keyLabel.length > 1;
    return Container(
      constraints: BoxConstraints(minWidth: 22 * t.scale),
      height: 22 * t.scale,
      padding: EdgeInsets.symmetric(horizontal: wide ? t.s1 + 2 : 0),
      alignment: Alignment.center,
      decoration: BoxDecoration(
        color: filled ? t.focus : t.panel,
        border: Border.all(color: t.ink, width: t.borderThin),
      ),
      child: Text(
        keyLabel,
        style: t.small.copyWith(
          fontWeight: FontWeight.w700,
          color: filled ? t.onFocus : t.ink,
        ),
      ),
    );
  }
}

class HintItem {
  const HintItem(this.key, this.label, {this.filled = false});
  final String key, label;
  final bool filled;
}

/// Bottom bar: `[A] OK  [B] BACK  [LB][RB] PAGE`.
class BrutalHintBar extends StatelessWidget {
  const BrutalHintBar({super.key, required this.hints, this.trailing});
  final List<HintItem> hints;
  final String? trailing;

  @override
  Widget build(BuildContext context) {
    final t = context.brutal;
    return Container(
      color: t.headerBar,
      padding: EdgeInsets.symmetric(horizontal: t.s4, vertical: t.s2),
      child: Row(
        children: [
          Expanded(
            child: Wrap(
              spacing: t.s4,
              runSpacing: t.s1,
              children: [
                for (final h in hints)
                  Row(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      for (final k in h.key.split('+')) ...[
                        KeyGlyph(k, filled: h.filled),
                        SizedBox(width: 2 * t.scale),
                      ],
                      SizedBox(width: t.s1),
                      Text(
                        h.label.toUpperCase(),
                        style: t.label.copyWith(color: t.onHeaderBar),
                      ),
                    ],
                  ),
              ],
            ),
          ),
          if (trailing != null)
            Text(trailing!, style: t.small.copyWith(color: t.onHeaderBar)),
        ],
      ),
    );
  }
}

/// `> install optiscaler ... ok` log lines.
class LogLine extends StatelessWidget {
  const LogLine(this.line, {super.key});
  final String line;

  @override
  Widget build(BuildContext context) {
    final t = context.brutal;
    final okEnd = line.trimRight().endsWith('ok');
    final err = RegExp(
      r'\b(err|error|failed|missing)\b',
      caseSensitive: false,
    ).hasMatch(line);
    final body = okEnd
        ? line.trimRight().substring(0, line.trimRight().length - 2)
        : line;
    return Text.rich(
      TextSpan(
        style: t.small.copyWith(color: err ? t.danger : t.ink),
        children: [
          TextSpan(text: '> $body'),
          if (okEnd)
            TextSpan(
              text: 'ok',
              style: TextStyle(color: t.ok, fontWeight: FontWeight.w700),
            ),
        ],
      ),
    );
  }
}

/// `FILE / SESSION / CORE` meta table: black key column, panel value column.
class KeyValueStrip extends StatelessWidget {
  const KeyValueStrip(this.rows, {super.key});
  final List<(String, String)> rows;

  @override
  Widget build(BuildContext context) {
    final t = context.brutal;
    return Container(
      decoration: BoxDecoration(
        border: Border.all(color: t.ink, width: t.border),
      ),
      child: Column(
        children: [
          for (var i = 0; i < rows.length; i++)
            Container(
              decoration: BoxDecoration(
                border: i == 0
                    ? null
                    : Border(
                        top: BorderSide(color: t.ink, width: t.borderThin),
                      ),
              ),
              child: IntrinsicHeight(
                child: Row(
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    Container(
                      width: 96 * t.scale,
                      color: t.headerBar,
                      padding: EdgeInsets.symmetric(
                        horizontal: t.s2,
                        vertical: t.s1,
                      ),
                      child: Text(
                        rows[i].$1.toUpperCase(),
                        style: t.small.copyWith(
                          color: t.onHeaderBar,
                          fontWeight: FontWeight.w600,
                        ),
                      ),
                    ),
                    Expanded(
                      child: Container(
                        color: t.panel,
                        padding: EdgeInsets.symmetric(
                          horizontal: t.s2,
                          vertical: t.s1,
                        ),
                        child: Text(
                          rows[i].$2,
                          style: t.small.copyWith(fontWeight: FontWeight.w600),
                        ),
                      ),
                    ),
                  ],
                ),
              ),
            ),
        ],
      ),
    );
  }
}

/// `>` prompt text input with a block cursor feel.
class CommandField extends StatelessWidget {
  const CommandField({
    super.key,
    required this.controller,
    this.hint = 'search',
    this.focusNode,
    this.onChanged,
    this.onSubmitted,
  });
  final TextEditingController controller;
  final String hint;
  final FocusNode? focusNode;
  final ValueChanged<String>? onChanged;
  final ValueChanged<String>? onSubmitted;

  @override
  Widget build(BuildContext context) {
    final t = context.brutal;
    return Container(
      height: t.buttonHeight,
      padding: EdgeInsets.symmetric(horizontal: t.s3),
      decoration: BoxDecoration(
        color: t.panel,
        border: Border.all(color: t.ink, width: t.border),
      ),
      child: Row(
        children: [
          PixelIcon(PixelGlyph.search, color: t.ink, size: t.iconSize),
          SizedBox(width: t.s2),
          Text('>', style: t.label),
          SizedBox(width: t.s2),
          Expanded(
            child: TextField(
              controller: controller,
              focusNode: focusNode,
              onChanged: onChanged,
              onSubmitted: onSubmitted,
              style: t.body,
              cursorColor: t.ink,
              cursorWidth: 8 * t.scale,
              cursorHeight: 16 * t.scale,
              cursorRadius: Radius.zero,
              decoration: InputDecoration(
                isCollapsed: true,
                border: InputBorder.none,
                hintText: hint,
                hintStyle: t.body.copyWith(color: t.mutedText),
              ),
            ),
          ),
        ],
      ),
    );
  }
}

/// `[x]ALL(12)` text toggle; the checked one is yellow.
class CheckFilter extends StatelessWidget {
  const CheckFilter({
    super.key,
    required this.label,
    required this.checked,
    this.count,
    this.onPressed,
  });
  final String label;
  final bool checked;
  final int? count;
  final VoidCallback? onPressed;

  @override
  Widget build(BuildContext context) {
    final t = context.brutal;
    return Pressable(
      onPressed: onPressed,
      builder: (c, st) {
        final hot = checked || st.active;
        return Container(
          height: t.rowHeight - 8 * t.scale,
          padding: EdgeInsets.symmetric(horizontal: t.s2),
          alignment: Alignment.centerLeft,
          color: hot ? t.focus : Colors.transparent,
          child: Text(
            '${checked ? '[x]' : '[ ]'}${label.toUpperCase()}${count != null ? '(${count!})' : ''}',
            style: t.label.copyWith(color: hot ? t.onFocus : t.ink),
            overflow: TextOverflow.ellipsis,
          ),
        );
      },
    );
  }
}

/// Hard progress bar: `[#####-----]`.
class ProgressCell extends StatelessWidget {
  const ProgressCell(this.value, {super.key, this.width = 120});
  final double value;
  final double width;

  @override
  Widget build(BuildContext context) {
    final t = context.brutal;
    final w = width * t.scale;
    return Container(
      width: w,
      height: 14 * t.scale,
      decoration: BoxDecoration(
        border: Border.all(color: t.ink, width: t.borderThin),
      ),
      alignment: Alignment.centerLeft,
      child: FractionallySizedBox(
        widthFactor: value.clamp(0, 1),
        child: Container(color: t.ink),
      ),
    );
  }
}

class EmptyState extends StatelessWidget {
  const EmptyState({
    super.key,
    required this.headline,
    required this.body,
    this.actions = const [],
  });
  final String headline, body;
  final List<Widget> actions;

  @override
  Widget build(BuildContext context) {
    final t = context.brutal;
    return Center(
      child: Padding(
        padding: EdgeInsets.all(t.s6),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(headline.toUpperCase(), style: t.display),
            SizedBox(height: t.s2),
            Text('> $body', style: t.body),
            SizedBox(height: t.s4),
            Wrap(spacing: t.s3, runSpacing: t.s3, children: actions),
          ],
        ),
      ),
    );
  }
}

/// Press and hold [duration] to confirm (replaces "are you sure").
/// Pointer: hold the mouse button. Keyboard / pad: hold Enter / Space / A.
class HoldToConfirm extends StatefulWidget {
  const HoldToConfirm({
    super.key,
    required this.label,
    required this.onConfirmed,
    this.duration = const Duration(milliseconds: 1000),
    this.icon,
    this.expand = true,
  });
  final String label;
  final VoidCallback onConfirmed;
  final Duration duration;
  final PixelGlyph? icon;
  final bool expand;

  @override
  State<HoldToConfirm> createState() => _HoldToConfirmState();
}

class _HoldToConfirmState extends State<HoldToConfirm> {
  final FocusNode _node = FocusNode();
  Timer? _timer;
  double _progress = 0;
  static const _tick = Duration(milliseconds: 50);

  void _start() {
    if (_timer != null) return;
    final steps = widget.duration.inMilliseconds / _tick.inMilliseconds;
    var n = 0;
    _timer = Timer.periodic(_tick, (tm) {
      n++;
      if (n >= steps) {
        _cancel();
        widget.onConfirmed();
      } else if (mounted) {
        setState(() => _progress = n / steps);
      }
    });
  }

  void _cancel() {
    _timer?.cancel();
    _timer = null;
    if (mounted) setState(() => _progress = 0);
  }

  @override
  void initState() {
    super.initState();
    PadBus.acceptHeld.addListener(_onPad);
  }

  /// A / Enter held on a focused button (pad and keyboard both feed this).
  void _onPad() {
    if (!_node.hasFocus) return;
    PadBus.acceptHeld.value ? _start() : _cancel();
  }

  @override
  void dispose() {
    PadBus.acceptHeld.removeListener(_onPad);
    _node.dispose();
    _timer?.cancel();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final t = context.brutal;
    return Focus(
      onKeyEvent: (node, e) {
        final hold =
            e.logicalKey == LogicalKeyboardKey.enter ||
            e.logicalKey == LogicalKeyboardKey.space ||
            e.logicalKey == LogicalKeyboardKey.gameButtonA;
        if (!hold) return KeyEventResult.ignored;
        if (e is KeyDownEvent) _start();
        if (e is KeyUpEvent) _cancel();
        return KeyEventResult.handled;
      },
      child: Listener(
        onPointerDown: (_) => _start(),
        onPointerUp: (_) => _cancel(),
        onPointerCancel: (_) => _cancel(),
        child: Pressable(
          focusNode: _node,
          onPressed: () {},
          builder: (c, st) {
            return Padding(
              padding: EdgeInsets.only(
                right: t.shadowOffset.dx,
                bottom: t.shadowOffset.dy,
              ),
              child: Container(
                height: t.buttonHeight,
                decoration: BoxDecoration(
                  color: st.active ? t.focus : t.panel,
                  border: Border.all(color: t.ink, width: t.border),
                  boxShadow: [
                    BoxShadow(color: t.shadow, offset: t.shadowOffset),
                  ],
                ),
                child: Stack(
                  children: [
                    Positioned.fill(
                      child: FractionallySizedBox(
                        alignment: Alignment.centerLeft,
                        widthFactor: _progress,
                        child: ColoredBox(color: t.danger),
                      ),
                    ),
                    Padding(
                      padding: EdgeInsets.symmetric(horizontal: t.s3),
                      child: Row(
                        mainAxisSize: widget.expand
                            ? MainAxisSize.max
                            : MainAxisSize.min,
                        children: [
                          if (widget.icon != null) ...[
                            PixelIcon(
                              widget.icon!,
                              color: _progress > 0.5
                                  ? Colors.white
                                  : (st.active ? t.onFocus : t.danger),
                              size: t.iconSize,
                            ),
                            SizedBox(width: t.s2),
                          ],
                          Text(
                            _progress > 0
                                ? 'KEEP HOLDING'
                                : widget.label.toUpperCase(),
                            style: t.label.copyWith(
                              color: _progress > 0.5
                                  ? Colors.white
                                  : (st.active ? t.onFocus : t.danger),
                            ),
                          ),
                        ],
                      ),
                    ),
                  ],
                ),
              ),
            );
          },
        ),
      ),
    );
  }
}

/// A `BrutalDialog`: panel with header strip, instant, 6 px shadow.
Future<T?> showBrutalDialog<T>(
  BuildContext context, {
  required String title,
  required Widget Function(BuildContext) body,
  required List<Widget> Function(BuildContext) actions,
  double width = 520,
}) {
  return showDialog<T>(
    context: context,
    barrierColor: const Color(0x66000000),
    animationStyle: AnimationStyle.noAnimation,
    builder: (ctx) {
      final t = ctx.brutal;
      return Dialog(
        backgroundColor: Colors.transparent,
        elevation: 0,
        insetPadding: EdgeInsets.all(t.s4),
        shape: const RoundedRectangleBorder(),
        child: ConstrainedBox(
          constraints: BoxConstraints(maxWidth: width * t.scale),
          child: Padding(
            padding: EdgeInsets.only(
              right: t.shadowOffsetLarge.dx,
              bottom: t.shadowOffsetLarge.dy,
            ),
            child: BrutalPanel(
              header: title,
              large: true,
              child: Column(
                mainAxisSize: MainAxisSize.min,
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  body(ctx),
                  SizedBox(height: t.s4),
                  Wrap(
                    alignment: WrapAlignment.end,
                    spacing: t.s3,
                    runSpacing: t.s3,
                    children: actions(ctx),
                  ),
                ],
              ),
            ),
          ),
        ),
      );
    },
  );
}
