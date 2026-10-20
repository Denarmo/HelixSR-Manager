/// Mouse + keyboard layout: a yellow header bar with the tabs inline, then
/// the page, then a hint bar. Console mode is a different shell entirely.
library;

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../../app/app_model.dart';
import '../brutal/brutal.dart';
import 'engine_page.dart';
import 'library_page.dart';
import 'settings_page.dart';

enum DesktopTab { games, engine, settings }

class DesktopShell extends StatefulWidget {
  const DesktopShell({super.key, required this.model});
  final AppModel model;

  @override
  State<DesktopShell> createState() => _DesktopShellState();
}

class _DesktopShellState extends State<DesktopShell> {
  DesktopTab tab = DesktopTab.games;

  @override
  Widget build(BuildContext context) {
    final m = widget.model;
    final installed = m.count(GameFilter.installed);
    return CallbackShortcuts(
      bindings: {
        const SingleActivator(LogicalKeyboardKey.f11): m.toggleConsoleMode,
        const SingleActivator(LogicalKeyboardKey.keyR, control: true): m.rescan,
        const SingleActivator(LogicalKeyboardKey.digit1, alt: true): () =>
            setState(() => tab = DesktopTab.games),
        const SingleActivator(LogicalKeyboardKey.digit2, alt: true): () =>
            setState(() => tab = DesktopTab.engine),
        const SingleActivator(LogicalKeyboardKey.digit3, alt: true): () =>
            setState(() => tab = DesktopTab.settings),
      },
      child: Focus(
        autofocus: true,
        child: GridPaper8(
          child: Column(
            children: [
              _Header(
                tab: tab,
                onTab: (v) => setState(() => tab = v),
                stat: '${m.games.length} GAMES // $installed ACTIVE',
                onConsole: m.toggleConsoleMode,
              ),
              Expanded(
                child: switch (tab) {
                  DesktopTab.games => LibraryPage(model: m),
                  DesktopTab.engine => EnginePage(model: m),
                  DesktopTab.settings => SettingsPage(model: m),
                },
              ),
              BrutalHintBar(
                hints: const [
                  HintItem('Enter', 'Open'),
                  HintItem('Arrows', 'Move'),
                  HintItem('/', 'Search'),
                  HintItem('Ctrl+R', 'Rescan'),
                  HintItem('F11', 'Console mode'),
                ],
                trailing: m.scanning ? 'SCANNING...' : 'v2.0',
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _Header extends StatelessWidget {
  const _Header({
    required this.tab,
    required this.onTab,
    required this.stat,
    required this.onConsole,
  });
  final DesktopTab tab;
  final ValueChanged<DesktopTab> onTab;
  final String stat;
  final VoidCallback onConsole;

  @override
  Widget build(BuildContext context) {
    final t = context.brutal;
    return Container(
      decoration: BoxDecoration(
        color: t.focus,
        border: Border(
          bottom: BorderSide(color: t.ink, width: t.border),
        ),
      ),
      padding: EdgeInsets.symmetric(horizontal: t.s4, vertical: t.s3),
      child: LayoutBuilder(
        builder: (context, box) {
          final compact = box.maxWidth < 760;
          return Row(
            children: [
              Text(
                'HELIXSR/',
                style: t.displaySmall.copyWith(color: t.onFocus),
              ),
              SizedBox(width: t.s6),
              for (final (v, name, icon) in [
                (DesktopTab.games, 'Games', PixelGlyph.gamepad),
                (DesktopTab.engine, 'Engine', PixelGlyph.chip),
                (DesktopTab.settings, 'Settings', PixelGlyph.gear),
              ])
                Padding(
                  padding: EdgeInsets.only(right: t.s3),
                  child: BrutalButton(
                    label: name,
                    icon: compact ? icon : null,
                    selected: tab == v,
                    onPressed: () => onTab(v),
                  ),
                ),
              const Spacer(),
              if (!compact) ...[
                Text(stat, style: t.label.copyWith(color: t.onFocus)),
                SizedBox(width: t.s4),
              ],
              BrutalButton(
                label: 'Console',
                icon: PixelGlyph.monitor,
                variant: ButtonVariant.dark,
                onPressed: onConsole,
              ),
            ],
          );
        },
      ),
    );
  }
}
