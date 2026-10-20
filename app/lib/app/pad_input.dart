/// Controller input. Gamepad events (via the `gamepads` plugin, normalised
/// across Windows/Linux) and the console-mode keyboard map become [PadAction]s:
/// the d-pad and left stick move focus, A activates, B pops the route; X, Y,
/// the bumpers, Start and Select go to [PadBus] for the console screens.
library;

import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:gamepads/gamepads.dart';

import 'app_model.dart';

enum PadAction {
  up,
  down,
  left,
  right,
  accept,
  back,
  x,
  y,
  lb,
  rb,
  start,
  select,
}

/// Broadcast bus of pad actions that no focus traversal handles itself.
class PadBus {
  PadBus._();
  static final StreamController<PadAction> _c =
      StreamController<PadAction>.broadcast();
  static Stream<PadAction> get stream => _c.stream;
  static void emit(PadAction a) => _c.add(a);

  /// True while A (or Enter) is held; hold-to-confirm buttons watch this.
  static final ValueNotifier<bool> acceptHeld = ValueNotifier(false);
}

class PadInput extends StatefulWidget {
  const PadInput({
    super.key,
    required this.child,
    required this.model,
    this.enabled = true,
  });
  final Widget child;
  final AppModel model;
  final bool enabled;

  @override
  State<PadInput> createState() => _PadInputState();
}

class _PadInputState extends State<PadInput> {
  StreamSubscription<NormalizedGamepadEvent>? _sub;
  final Map<PadAction, Timer> _repeat = {};
  final Set<PadAction> _stickDirs = {};

  @override
  void initState() {
    super.initState();
    if (widget.enabled) {
      try {
        _sub = Gamepads.normalizedEvents.listen(_onEvent, onError: (_) {});
      } catch (_) {
        // No gamepad backend on this platform: keyboard map only.
      }
    }
  }

  @override
  void dispose() {
    _sub?.cancel();
    for (final t in _repeat.values) {
      t.cancel();
    }
    super.dispose();
  }

  static const _buttons = <GamepadButton, PadAction>{
    GamepadButton.a: PadAction.accept,
    GamepadButton.b: PadAction.back,
    GamepadButton.x: PadAction.x,
    GamepadButton.y: PadAction.y,
    GamepadButton.leftBumper: PadAction.lb,
    GamepadButton.rightBumper: PadAction.rb,
    GamepadButton.start: PadAction.start,
    GamepadButton.back: PadAction.select,
    GamepadButton.dpadUp: PadAction.up,
    GamepadButton.dpadDown: PadAction.down,
    GamepadButton.dpadLeft: PadAction.left,
    GamepadButton.dpadRight: PadAction.right,
  };

  void _onEvent(NormalizedGamepadEvent e) {
    final button = e.button;
    if (button != null) {
      final a = _buttons[button];
      if (a == null) return;
      _setHeld(a, e.value != 0);
      return;
    }
    final axis = e.axis;
    if (axis == GamepadAxis.leftStickX) {
      _stick(PadAction.left, PadAction.right, e.value);
    } else if (axis == GamepadAxis.leftStickY) {
      _stick(PadAction.down, PadAction.up, e.value);
    }
  }

  void _stick(PadAction neg, PadAction pos, double v) {
    _setHeld(neg, v < -0.6, stick: true);
    _setHeld(pos, v > 0.6, stick: true);
  }

  bool _isDir(PadAction a) =>
      a == PadAction.up ||
      a == PadAction.down ||
      a == PadAction.left ||
      a == PadAction.right;

  void _setHeld(PadAction a, bool down, {bool stick = false}) {
    if (stick) {
      if (down == _stickDirs.contains(a)) return;
      down ? _stickDirs.add(a) : _stickDirs.remove(a);
    }
    if (a == PadAction.accept) PadBus.acceptHeld.value = down;
    if (!down) {
      _repeat.remove(a)?.cancel();
      return;
    }
    if (_repeat.containsKey(a)) return;
    _fire(a);
    if (_isDir(a)) {
      // Held d-pad repeats: 350 ms delay, then every 90 ms.
      _repeat[a] = Timer(const Duration(milliseconds: 350), () {
        _repeat[a] = Timer.periodic(
          const Duration(milliseconds: 90),
          (_) => _fire(a),
        );
      });
    } else {
      _repeat[a] = Timer(const Duration(days: 1), () {});
    }
  }

  void _fire(PadAction a) {
    if (!mounted) return;
    final m = widget.model;
    // The first pad press hands the UI to the console layout.
    if (!m.consoleMode && m.settings.uiMode == 'auto') {
      m.setConsoleMode(true);
      return;
    }
    handlePadAction(context, a);
  }

  KeyEventResult _onKey(FocusNode node, KeyEvent e) {
    if (!widget.model.consoleMode) return KeyEventResult.ignored;
    final k = e.logicalKey;
    if (k == LogicalKeyboardKey.enter ||
        k == LogicalKeyboardKey.space ||
        k == LogicalKeyboardKey.gameButtonA) {
      if (e is KeyDownEvent) PadBus.acceptHeld.value = true;
      if (e is KeyUpEvent) PadBus.acceptHeld.value = false;
      return KeyEventResult.ignored; // ActivateIntent still runs
    }
    if (e is! KeyDownEvent && e is! KeyRepeatEvent)
      return KeyEventResult.ignored;
    final editing =
        primaryFocus?.context?.findAncestorWidgetOfExactType<EditableText>() !=
        null;
    if (!editing &&
        (k == LogicalKeyboardKey.arrowLeft ||
            k == LogicalKeyboardKey.arrowRight)) {
      if (PadSide.step(k == LogicalKeyboardKey.arrowRight ? 1 : -1)) {
        return KeyEventResult.handled;
      }
    }
    final PadAction? a = switch (k) {
      LogicalKeyboardKey.escape ||
      LogicalKeyboardKey.gameButtonB => PadAction.back,
      LogicalKeyboardKey.backspace when !editing => PadAction.back,
      LogicalKeyboardKey.keyX when !editing => PadAction.x,
      LogicalKeyboardKey.gameButtonX => PadAction.x,
      LogicalKeyboardKey.keyY when !editing => PadAction.y,
      LogicalKeyboardKey.gameButtonY => PadAction.y,
      LogicalKeyboardKey.keyQ when !editing => PadAction.lb,
      LogicalKeyboardKey.pageUp ||
      LogicalKeyboardKey.gameButtonLeft1 => PadAction.lb,
      LogicalKeyboardKey.keyE when !editing => PadAction.rb,
      LogicalKeyboardKey.pageDown ||
      LogicalKeyboardKey.gameButtonRight1 => PadAction.rb,
      LogicalKeyboardKey.home ||
      LogicalKeyboardKey.gameButtonStart => PadAction.start,
      LogicalKeyboardKey.end ||
      LogicalKeyboardKey.gameButtonSelect => PadAction.select,
      _ => null,
    };
    if (a == null || e is KeyRepeatEvent && a != PadAction.back)
      return KeyEventResult.ignored;
    handlePadAction(context, a);
    return KeyEventResult.handled;
  }

  @override
  Widget build(BuildContext context) => Focus(
    canRequestFocus: false,
    skipTraversal: true,
    onKeyEvent: _onKey,
    child: widget.child,
  );
}

/// Applies a pad action to the focused UI. Public so tests can drive it.
void handlePadAction(BuildContext context, PadAction a) {
  final focus = primaryFocus;
  final ctx = focus?.context ?? context;
  switch (a) {
    case PadAction.up:
    case PadAction.down:
    case PadAction.left:
    case PadAction.right:
      if ((a == PadAction.left || a == PadAction.right) &&
          PadSide.step(a == PadAction.right ? 1 : -1)) {
        return;
      }
      if (focus == null || focus == FocusManager.instance.rootScope) {
        FocusScope.of(context).nextFocus();
        return;
      }
      final dir = switch (a) {
        PadAction.up => TraversalDirection.up,
        PadAction.down => TraversalDirection.down,
        PadAction.left => TraversalDirection.left,
        _ => TraversalDirection.right,
      };
      _invoke(ctx, DirectionalFocusIntent(dir));
    case PadAction.accept:
      _invoke(ctx, const ActivateIntent());
      PadBus.emit(a);
    case PadAction.back:
      final nav = Navigator.maybeOf(ctx);
      if (nav != null && nav.canPop()) {
        nav.maybePop();
      } else {
        PadBus.emit(a);
      }
    default:
      PadBus.emit(a);
  }
}

void _invoke<T extends Intent>(BuildContext ctx, T intent) =>
    Actions.maybeInvoke(ctx, intent);

/// The focused stepper row (console `LABEL < VALUE >`) claims left/right so
/// they change its value instead of moving focus; up/down still move.
class PadSide {
  PadSide._();
  static Object? _owner;
  static void Function(int dir)? _fn;

  static void claim(Object owner, void Function(int dir) fn) {
    _owner = owner;
    _fn = fn;
  }

  static void release(Object owner) {
    if (_owner == owner) {
      _owner = null;
      _fn = null;
    }
  }

  /// Runs the claimed handler; false when no row claimed the direction.
  static bool step(int dir) {
    final f = _fn;
    if (f == null) return false;
    f(dir);
    return true;
  }
}
