/// One focus/hover/press model for every interactive brutalist widget.
/// Enter, Space and the pad's A button arrive as ActivateIntent; hover moves
/// focus in desktop mode, so there is only ever one highlighted control.
library;

import 'package:flutter/gestures.dart';
import 'package:flutter/material.dart';

import 'tokens.dart';

@immutable
class PressState {
  const PressState({
    required this.focused,
    required this.hovered,
    required this.pressed,
    required this.enabled,
  });
  final bool focused, hovered, pressed, enabled;

  /// Highlighted for the user: keyboard/pad focus or mouse hover.
  bool get active => enabled && (focused || hovered);
}

class Pressable extends StatefulWidget {
  const Pressable({
    super.key,
    required this.builder,
    this.onPressed,
    this.onSecondaryPressed,
    this.focusNode,
    this.autofocus = false,
    this.onFocusChange,
    this.hoverFocus = true,
    this.centerOnFocus = false,
    this.semanticLabel,
  });

  final Widget Function(BuildContext context, PressState state) builder;
  final VoidCallback? onPressed;
  final VoidCallback? onSecondaryPressed;
  final FocusNode? focusNode;
  final bool autofocus;
  final ValueChanged<bool>? onFocusChange;

  /// Mouse hover moves keyboard focus here (desktop mode).
  final bool hoverFocus;

  /// Scroll so the focused control sits mid-viewport (cover shelf).
  final bool centerOnFocus;
  final String? semanticLabel;

  @override
  State<Pressable> createState() => _PressableState();
}

class _PressableState extends State<Pressable> {
  bool _hasFocus = false,
      _highlight = false,
      _hovered = false,
      _pressed = false;

  /// Focus is drawn after keyboard/pad use; console mode always draws it.
  bool get _focused => _hasFocus && (_highlight || context.brutal.console);
  FocusNode? _own;
  FocusNode get _node => widget.focusNode ?? (_own ??= FocusNode());

  bool get _enabled => widget.onPressed != null;

  @override
  void dispose() {
    _own?.dispose();
    super.dispose();
  }

  void _gained() {
    widget.onFocusChange?.call(true);
    if (!mounted) return;
    Scrollable.ensureVisible(
      context,
      duration: Duration.zero,
      alignment: widget.centerOnFocus ? 0.5 : 0,
      alignmentPolicy: widget.centerOnFocus
          ? ScrollPositionAlignmentPolicy.explicit
          : ScrollPositionAlignmentPolicy.keepVisibleAtEnd,
    );
  }

  void _activate() {
    if (!_enabled) return;
    setState(() => _pressed = true);
    widget.onPressed!();
    Future<void>.delayed(BrutalTokens.release, () {
      if (mounted) setState(() => _pressed = false);
    });
  }

  @override
  Widget build(BuildContext context) {
    final state = PressState(
      focused: _focused,
      hovered: _hovered,
      pressed: _pressed,
      enabled: _enabled,
    );
    return Semantics(
      button: true,
      enabled: _enabled,
      label: widget.semanticLabel,
      child: FocusableActionDetector(
        focusNode: _node,
        autofocus: widget.autofocus,
        enabled: _enabled,
        mouseCursor: _enabled ? SystemMouseCursors.click : MouseCursor.defer,
        onFocusChange: (v) {
          setState(() => _hasFocus = v);
          if (v) {
            if (_focused) _gained();
          } else {
            widget.onFocusChange?.call(false);
          }
        },
        onShowFocusHighlight: (v) {
          setState(() => _highlight = v);
          if (v && _hasFocus) _gained();
        },
        onShowHoverHighlight: (v) {
          setState(() => _hovered = v);
          if (v && widget.hoverFocus && _enabled && !_node.hasFocus) {
            _node.requestFocus();
          }
        },
        actions: {
          ActivateIntent: CallbackAction<ActivateIntent>(
            onInvoke: (_) {
              _activate();
              return null;
            },
          ),
          ButtonActivateIntent: CallbackAction<ButtonActivateIntent>(
            onInvoke: (_) {
              _activate();
              return null;
            },
          ),
        },
        child: Listener(
          onPointerDown: (e) {
            if (!mounted) return;
            if (e.kind == PointerDeviceKind.mouse &&
                e.buttons == kSecondaryMouseButton) {
              widget.onSecondaryPressed?.call();
              return;
            }
            if (_enabled) setState(() => _pressed = true);
          },
          onPointerUp: (_) {
            if (mounted && _pressed) setState(() => _pressed = false);
          },
          onPointerCancel: (_) {
            if (mounted && _pressed) setState(() => _pressed = false);
          },
          child: GestureDetector(
            behavior: HitTestBehavior.opaque,
            onTap: _enabled ? widget.onPressed : null,
            child: widget.builder(context, state),
          ),
        ),
      ),
    );
  }
}
