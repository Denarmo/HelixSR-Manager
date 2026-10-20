/// Full-screen game page for the controller layout: cover on the left, one
/// big row per setting on the right. Left/right change a value in place, A
/// runs an action, hold A uninstalls, B goes back.
library;

import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../../app/app_model.dart';
import '../../engine/engine.dart';
import '../brutal/brutal.dart';
import '../common/game_cover.dart';
import '../common/labels.dart';
import 'console_widgets.dart';

class ConsoleGameScreen extends StatelessWidget {
  const ConsoleGameScreen({
    super.key,
    required this.model,
    required this.gameId,
  });
  final AppModel model;
  final String gameId;

  static T cycle<T>(List<T> v, T cur, int dir) =>
      v[(v.indexOf(cur) + dir + v.length) % v.length];

  Future<void> _fail(BuildContext context, String title, String message) =>
      showBrutalDialog<void>(
        context,
        title: title,
        body: (c) => Text(message, style: c.brutal.title),
        actions: (c) => [
          BrutalButton(
            label: 'OK',
            variant: ButtonVariant.primary,
            autofocus: true,
            onPressed: () => Navigator.of(c).pop(),
          ),
        ],
      );

  @override
  Widget build(BuildContext context) {
    final t = context.brutal;
    return Scaffold(
      body: GridPaper8(
        child: ListenableBuilder(
          listenable: model,
          builder: (context, _) {
            final g = model.games.where((x) => x.id == gameId).firstOrNull;
            if (g == null) return const SizedBox.shrink();
            final busy = model.isBusy(g);
            final built = model.core?.weightsBuilt ?? false;
            final choices = routeChoices(model.core);
            final fgLocked = g.fgMode.startsWith('dlssg_');
            return Column(
              children: [
                Container(
                  color: t.headerBar,
                  padding: EdgeInsets.symmetric(
                    horizontal: t.s6,
                    vertical: t.s3,
                  ),
                  child: Row(
                    children: [
                      const KeyGlyph('B'),
                      SizedBox(width: t.s2),
                      Text(
                        'BACK',
                        style: t.label.copyWith(color: t.onHeaderBar),
                      ),
                      SizedBox(width: t.s6),
                      Expanded(
                        child: Text(
                          BrutalTokens.fileName(g.name),
                          style: t.displaySmall.copyWith(color: t.focus),
                          overflow: TextOverflow.ellipsis,
                        ),
                      ),
                    ],
                  ),
                ),
                Expanded(
                  child: Padding(
                    padding: EdgeInsets.all(t.s6),
                    child: Row(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        SizedBox(
                          width: 240 * t.scale,
                          child: Column(
                            crossAxisAlignment: CrossAxisAlignment.stretch,
                            children: [
                              AspectRatio(
                                aspectRatio: 2 / 3,
                                child: Padding(
                                  padding: EdgeInsets.only(
                                    right: t.shadowOffsetLarge.dx,
                                    bottom: t.shadowOffsetLarge.dy,
                                  ),
                                  child: DecoratedBox(
                                    decoration: BoxDecoration(
                                      boxShadow: [
                                        BoxShadow(
                                          color: t.shadow,
                                          offset: t.shadowOffsetLarge,
                                        ),
                                      ],
                                    ),
                                    child: GameCover(g),
                                  ),
                                ),
                              ),
                              SizedBox(height: t.s3),
                              Align(
                                alignment: Alignment.centerLeft,
                                child: Sticker(
                                  busy
                                      ? 'Working'
                                      : (g.installed
                                            ? 'Active ${g.version}'
                                            : 'Not installed'),
                                  color: busy
                                      ? t.primary
                                      : (g.installed ? t.ok : t.muted),
                                  fg: busy || g.installed
                                      ? Colors.white
                                      : t.ink,
                                ),
                              ),
                              SizedBox(height: t.s3),
                              Wrap(
                                spacing: t.s1,
                                runSpacing: t.s1,
                                children: [for (final tag in g.tags) Tag(tag)],
                              ),
                            ],
                          ),
                        ),
                        SizedBox(width: t.s8),
                        Expanded(
                          child: SingleChildScrollView(
                            child: Column(
                              crossAxisAlignment: CrossAxisAlignment.stretch,
                              children: [
                                ConsoleRow(
                                  label: busy
                                      ? 'Working...'
                                      : (g.installed ? 'Reinstall' : 'Install'),
                                  sub: built
                                      ? g.routeDisplay
                                      : 'network not built: open ENGINE first',
                                  icon: PixelGlyph.download,
                                  primary: true,
                                  autofocus: true,
                                  onPressed: busy || !built
                                      ? null
                                      : () async {
                                          final err = await model.install(g);
                                          if (err != null && context.mounted) {
                                            await _fail(
                                              context,
                                              'Install failed',
                                              err,
                                            );
                                          }
                                        },
                                ),
                                SizedBox(height: t.s3),
                                ConsoleRow(
                                  label: 'Method',
                                  value: routeName(
                                    choices.contains(g.route)
                                        ? g.route
                                        : choices.first,
                                  ),
                                  onStep: busy
                                      ? null
                                      : (d) => model.edit(
                                          g,
                                          (x) => x.route = cycle(
                                            choices,
                                            choices.contains(x.route)
                                                ? x.route
                                                : choices.first,
                                            d,
                                          ),
                                        ),
                                ),
                                if (g.route == 'optiscaler') ...[
                                  SizedBox(height: t.s3),
                                  ConsoleRow(
                                    label: 'Proxy DLL',
                                    value: g.optiDllName,
                                    onStep: busy
                                        ? null
                                        : (d) => model.edit(
                                            g,
                                            (x) => x.optiDllName = cycle(
                                              optiDllNames,
                                              x.optiDllName,
                                              d,
                                            ),
                                          ),
                                  ),
                                  SizedBox(height: t.s3),
                                  ConsoleRow(
                                    label: 'Frame gen',
                                    value: fgName(g.fgMode),
                                    onStep: busy
                                        ? null
                                        : (d) => model.edit(
                                            g,
                                            (x) => x.fgMode = cycle(
                                              fgModes,
                                              x.fgMode,
                                              d,
                                            ),
                                          ),
                                  ),
                                  SizedBox(height: t.s3),
                                  ConsoleRow(
                                    label: 'FakeNvapi',
                                    value: g.useFakeNvapi || fgLocked
                                        ? 'on'
                                        : 'off',
                                    sub: fgLocked
                                        ? 'required by DLSS-G frame generation'
                                        : null,
                                    onStep: busy || fgLocked
                                        ? null
                                        : (_) => model.edit(
                                            g,
                                            (x) => x.useFakeNvapi =
                                                !x.useFakeNvapi,
                                          ),
                                  ),
                                ],
                                if (g.isReEngine || g.installReFramework) ...[
                                  SizedBox(height: t.s3),
                                  ConsoleRow(
                                    label: 'REFramework',
                                    value: g.installReFramework ? 'on' : 'off',
                                    onStep: busy
                                        ? null
                                        : (_) => model.edit(
                                            g,
                                            (x) => x.installReFramework =
                                                !x.installReFramework,
                                          ),
                                  ),
                                ],
                                if (g.appId != null) ...[
                                  SizedBox(height: t.s3),
                                  ConsoleRow(
                                    label: 'Launch',
                                    icon: PixelGlyph.play,
                                    onPressed: () => launchGame(g),
                                  ),
                                ],
                                SizedBox(height: t.s3),
                                ConsoleRow(
                                  label: 'Logs',
                                  icon: PixelGlyph.info,
                                  onPressed: () => Navigator.of(context).push(
                                    MaterialPageRoute<void>(
                                      builder: (_) => _LogScreen(game: g),
                                    ),
                                  ),
                                ),
                                if (!Platform.isWindows &&
                                    g.protonLaunchOption.isNotEmpty) ...[
                                  SizedBox(height: t.s3),
                                  ConsoleRow(
                                    label: 'Copy Steam launch option',
                                    sub: g.protonLaunchOption,
                                    onPressed: () {
                                      Clipboard.setData(
                                        ClipboardData(
                                          text: g.protonLaunchOption,
                                        ),
                                      );
                                      model.log('copied launch option ... ok');
                                    },
                                  ),
                                ],
                                if (g.installed) ...[
                                  SizedBox(height: t.s6),
                                  HoldToConfirm(
                                    label: 'Hold A to uninstall',
                                    icon: PixelGlyph.trash,
                                    onConfirmed: () async {
                                      final err = await model.uninstall(g);
                                      if (err != null && context.mounted) {
                                        await _fail(
                                          context,
                                          'Uninstall failed',
                                          err,
                                        );
                                      }
                                    },
                                  ),
                                ],
                                SizedBox(height: t.s4),
                                for (final l
                                    in model.activity.reversed
                                        .take(3)
                                        .toList()
                                        .reversed)
                                  LogLine(l),
                              ],
                            ),
                          ),
                        ),
                      ],
                    ),
                  ),
                ),
                const BrutalHintBar(
                  hints: [
                    HintItem('A', 'Run', filled: true),
                    HintItem('LR', 'Change value'),
                    HintItem('B', 'Back'),
                  ],
                ),
              ],
            );
          },
        ),
      ),
    );
  }
}

class _LogScreen extends StatefulWidget {
  const _LogScreen({required this.game});
  final GameInfo game;

  @override
  State<_LogScreen> createState() => _LogScreenState();
}

class _LogScreenState extends State<_LogScreen> {
  final scroll = ScrollController();
  bool helix = true;

  @override
  void dispose() {
    scroll.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final t = context.brutal;
    final logs = readGameLogs(widget.game);
    final text = helix ? logs.helixsr : logs.optiscaler;
    return Scaffold(
      body: GridPaper8(
        child: Column(
          children: [
            Container(
              color: t.headerBar,
              padding: EdgeInsets.symmetric(horizontal: t.s6, vertical: t.s3),
              child: Row(
                children: [
                  const KeyGlyph('B'),
                  SizedBox(width: t.s2),
                  Text('BACK', style: t.label.copyWith(color: t.onHeaderBar)),
                  SizedBox(width: t.s6),
                  Text(
                    helix ? 'HELIXSR.LOG' : 'OPTISCALER.LOG',
                    style: t.displaySmall.copyWith(color: t.focus),
                  ),
                ],
              ),
            ),
            Expanded(
              child: Padding(
                padding: EdgeInsets.all(t.s6),
                child: Focus(
                  autofocus: true,
                  onKeyEvent: (n, e) {
                    if (e is KeyUpEvent) return KeyEventResult.ignored;
                    final k = e.logicalKey;
                    if (k == LogicalKeyboardKey.arrowDown) {
                      scroll.jumpTo(
                        (scroll.offset + 120 * t.scale).clamp(
                          0,
                          scroll.position.maxScrollExtent,
                        ),
                      );
                      return KeyEventResult.handled;
                    }
                    if (k == LogicalKeyboardKey.arrowUp) {
                      scroll.jumpTo(
                        (scroll.offset - 120 * t.scale).clamp(
                          0,
                          scroll.position.maxScrollExtent,
                        ),
                      );
                      return KeyEventResult.handled;
                    }
                    if (k == LogicalKeyboardKey.enter ||
                        k == LogicalKeyboardKey.gameButtonA) {
                      setState(() => helix = !helix);
                      return KeyEventResult.handled;
                    }
                    return KeyEventResult.ignored;
                  },
                  child: Container(
                    color: const Color(0xFF000000),
                    padding: EdgeInsets.all(t.s3),
                    child: SingleChildScrollView(
                      controller: scroll,
                      child: Text(
                        text.isEmpty
                            ? '> no log yet: start the game once'
                            : text,
                        style: t.small.copyWith(color: const Color(0xFFF2F2EC)),
                      ),
                    ),
                  ),
                ),
              ),
            ),
            const BrutalHintBar(
              hints: [
                HintItem('UD', 'Scroll'),
                HintItem('A', 'Switch log', filled: true),
                HintItem('B', 'Back'),
              ],
            ),
          ],
        ),
      ),
    );
  }
}
