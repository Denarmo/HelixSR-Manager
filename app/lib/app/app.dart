import 'package:flutter/material.dart';

import '../ui/brutal/brutal.dart';
import '../ui/console/console_shell.dart';
import '../ui/desktop/desktop_shell.dart';
import 'app_model.dart';
import 'pad_input.dart';

class HelixApp extends StatelessWidget {
  const HelixApp({super.key, required this.model, this.enablePad = true});
  final AppModel model;

  /// Gamepad input needs the platform plugin; widget tests turn it off.
  final bool enablePad;

  BrutalTokens _tokens(Brightness system) {
    final s = model.settings;
    final accent = BrutalAccent.parse(s.accent);
    final b = switch (s.theme) {
      'ink' => Brightness.dark,
      'system' => system,
      _ => Brightness.light,
    };
    return BrutalTokens.forBrightness(b, accent: accent);
  }

  @override
  Widget build(BuildContext context) {
    return ListenableBuilder(
      listenable: model,
      builder: (context, _) {
        final system = MediaQuery.platformBrightnessOf(context);
        final base = _tokens(system);
        return MaterialApp(
          title: 'HelixSR Manager',
          debugShowCheckedModeBanner: false,
          theme: base.toTheme(),
          builder: (context, child) {
            // Console mode scales every metric with the window height so the
            // UI reads from the sofa (1x at 720p, 1.5x at 1080p, 2x at 4K).
            final h = MediaQuery.sizeOf(context).height;
            final tokens = model.consoleMode
                ? base.at(
                    BrutalDensity.console,
                    (h / 720).clamp(1.0, 2.4) * 1.15,
                  )
                : base;
            return Theme(
              data: tokens.toTheme(),
              child: PadInput(enabled: enablePad, model: model, child: child!),
            );
          },
          home: Scaffold(
            body: model.consoleMode
                ? ConsoleShell(model: model)
                : DesktopShell(model: model),
          ),
        );
      },
    );
  }
}
