/// Controller / couch layout. A separate design from the desktop one: a cover
/// shelf instead of a table, one big action per row instead of an inspector,
/// every control reachable with a d-pad, A / B / X / Y and the bumpers.
library;

import 'package:flutter/material.dart';

import '../../app/app_model.dart';
import '../../app/pad_input.dart';
import '../../engine/engine.dart';
import '../brutal/brutal.dart';
import '../common/game_cover.dart';
import '../common/labels.dart';
import 'console_widgets.dart';
import 'folder_picker.dart';
import 'game_screen.dart';

class ConsoleShell extends StatefulWidget {
  const ConsoleShell({super.key, required this.model});
  final AppModel model;

  @override
  State<ConsoleShell> createState() => _ConsoleShellState();
}

class _ConsoleShellState extends State<ConsoleShell> {
  int page = 0;
  static const pages = ['Games', 'Engine', 'System'];

  AppModel get m => widget.model;

  void go(int delta) => setState(() => page = (page + delta) % pages.length);

  @override
  Widget build(BuildContext context) {
    final t = context.brutal;
    return PadListener(
      onAction: (a) {
        if (a == PadAction.lb) go(pages.length - 1);
        if (a == PadAction.rb) go(1);
      },
      child: GridPaper8(
        child: ListenableBuilder(
          listenable: m,
          builder: (context, _) => Column(
            children: [
              ConsoleHeader(
                pages: pages,
                index: page,
                right: m.scanning
                    ? 'SCANNING...'
                    : '${m.games.length} GAMES // ${m.count(GameFilter.installed)} ACTIVE',
              ),
              Expanded(
                child: switch (page) {
                  0 => _GamesPage(model: m),
                  1 => _EnginePage(model: m),
                  _ => _SystemPage(model: m),
                },
              ),
              BrutalHintBar(
                hints: switch (page) {
                  0 => const [
                    HintItem('A', 'Open', filled: true),
                    HintItem('X', 'Sort'),
                    HintItem('Y', 'Filter'),
                    HintItem('LB+RB', 'Page'),
                  ],
                  1 => const [
                    HintItem('A', 'Select', filled: true),
                    HintItem('Y', 'Rescan'),
                    HintItem('LB+RB', 'Page'),
                  ],
                  _ => const [
                    HintItem('A', 'Select', filled: true),
                    HintItem('LR', 'Change'),
                    HintItem('LB+RB', 'Page'),
                  ],
                },
                trailing: 'KEYS  ARROWS ENTER ESC X Y Q E',
              ),
              SizedBox(height: t.s1 / 2),
            ],
          ),
        ),
      ),
    );
  }
}

// ---- GAMES -----------------------------------------------------------------

class _GamesPage extends StatefulWidget {
  const _GamesPage({required this.model});
  final AppModel model;

  @override
  State<_GamesPage> createState() => _GamesPageState();
}

class _GamesPageState extends State<_GamesPage> {
  String? focusedId;

  AppModel get m => widget.model;

  void _open(GameInfo g) {
    m.select(g);
    Navigator.of(context).push(
      MaterialPageRoute<void>(
        builder: (_) => ConsoleGameScreen(model: m, gameId: g.id),
      ),
    );
  }

  static const _filters = GameFilter.values;
  static String _filterName(GameFilter f) => switch (f) {
    GameFilter.all => 'All',
    GameFilter.installed => 'Active',
    GameFilter.notInstalled => 'Not installed',
    GameFilter.dlss => 'DLSS',
    GameFilter.reEngine => 'RE Engine',
  };

  @override
  Widget build(BuildContext context) {
    final t = context.brutal;
    final games = m.visible;
    final focused =
        games.where((g) => g.id == focusedId).firstOrNull ?? games.firstOrNull;
    return PadListener(
      onAction: (a) {
        if (a == PadAction.y) {
          m.setFilter(_filters[(m.filter.index + 1) % _filters.length]);
        } else if (a == PadAction.x) {
          m.sortBy(
            SortKey.values[(m.sortKey.index + 1) % SortKey.values.length],
          );
        }
      },
      child: Padding(
        padding: EdgeInsets.fromLTRB(t.s6, t.s4, 0, t.s4),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                const KeyGlyph('Y'),
                SizedBox(width: t.s2),
                Text(
                  'FILTER ${_filterName(m.filter).toUpperCase()} (${m.count(m.filter)})',
                  style: t.label,
                ),
                SizedBox(width: t.s6),
                const KeyGlyph('X'),
                SizedBox(width: t.s2),
                Text(
                  'SORT ${m.sortKey.name.toUpperCase()} ${m.sortAscending ? '↓' : '↑'}',
                  style: t.label,
                ),
              ],
            ),
            SizedBox(height: t.s4),
            if (games.isEmpty)
              Expanded(
                child: EmptyState(
                  headline: m.scanning ? 'Scanning...' : 'No games found.',
                  body: m.scanning
                      ? 'looking through your Steam libraries'
                      : 'add a folder to start',
                  actions: [
                    BrutalButton(
                      label: 'Add folder',
                      icon: PixelGlyph.folder,
                      variant: ButtonVariant.primary,
                      autofocus: true,
                      onPressed: () => pickFolderConsole(context, m),
                    ),
                  ],
                ),
              )
            else ...[
              SizedBox(
                height: 250 * t.scale,
                child: ListView.builder(
                  scrollDirection: Axis.horizontal,
                  clipBehavior: Clip.none,
                  padding: EdgeInsets.only(right: t.s8, bottom: t.s3),
                  itemCount: games.length,
                  itemBuilder: (context, i) {
                    final g = games[i];
                    return _PosterCard(
                      game: g,
                      busy: m.isBusy(g),
                      autofocus: i == 0,
                      onFocus: () {
                        if (focusedId != g.id) setState(() => focusedId = g.id);
                      },
                      onOpen: () => _open(g),
                    );
                  },
                ),
              ),
              SizedBox(height: t.s4),
              if (focused != null)
                Expanded(
                  child: Padding(
                    padding: EdgeInsets.only(
                      right: t.s6 + t.shadowOffsetLarge.dx,
                    ),
                    child: _NowSelected(game: focused, busy: m.isBusy(focused)),
                  ),
                ),
            ],
          ],
        ),
      ),
    );
  }
}

class _PosterCard extends StatelessWidget {
  const _PosterCard({
    required this.game,
    required this.busy,
    required this.autofocus,
    required this.onFocus,
    required this.onOpen,
  });
  final GameInfo game;
  final bool busy, autofocus;
  final VoidCallback onFocus, onOpen;

  @override
  Widget build(BuildContext context) {
    final t = context.brutal;
    return Pressable(
      autofocus: autofocus,
      centerOnFocus: true,
      onPressed: onOpen,
      onFocusChange: (f) {
        if (f) onFocus();
      },
      builder: (c, st) {
        final hot = st.active;
        // The focused poster is drawn larger by shrinking its margin (a hard
        // size change, no animation).
        final v = hot ? 0.0 : 16 * t.scale;
        return Padding(
          padding: EdgeInsets.fromLTRB(
            t.s3,
            v,
            t.s3 + t.shadowOffset.dx,
            v + t.shadowOffset.dy,
          ),
          child: Container(
            width: 150 * t.scale,
            decoration: BoxDecoration(
              color: hot ? t.focus : t.panel,
              border: Border.all(color: t.ink, width: t.border),
              boxShadow: [
                BoxShadow(
                  color: t.shadow,
                  offset: hot ? t.shadowOffsetLarge : t.shadowOffset,
                ),
              ],
            ),
            padding: EdgeInsets.all(hot ? 6 * t.scale : 0),
            child: Stack(
              fit: StackFit.expand,
              children: [
                GameCover(game, border: false),
                Positioned(
                  left: 0,
                  top: 0,
                  child: Container(
                    color: busy ? t.primary : (game.installed ? t.ok : t.ink),
                    padding: EdgeInsets.symmetric(
                      horizontal: t.s2,
                      vertical: 2,
                    ),
                    child: Text(
                      busy ? 'WORKING' : (game.installed ? 'ACTIVE' : 'OFF'),
                      style: t.small.copyWith(
                        color: Colors.white,
                        fontWeight: FontWeight.w700,
                      ),
                    ),
                  ),
                ),
              ],
            ),
          ),
        );
      },
    );
  }
}

class _NowSelected extends StatelessWidget {
  const _NowSelected({required this.game, required this.busy});
  final GameInfo game;
  final bool busy;

  @override
  Widget build(BuildContext context) {
    final t = context.brutal;
    return Container(
      decoration: BoxDecoration(
        color: const Color(0xFF000000),
        border: Border.all(color: t.ink, width: t.border),
        boxShadow: [BoxShadow(color: t.shadow, offset: t.shadowOffsetLarge)],
      ),
      padding: EdgeInsets.all(t.s4),
      child: Row(
        children: [
          Expanded(
            child: Column(
              mainAxisAlignment: MainAxisAlignment.center,
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                FittedBox(
                  fit: BoxFit.scaleDown,
                  alignment: Alignment.centerLeft,
                  child: Text(
                    BrutalTokens.fileName(game.name),
                    style: t.display.copyWith(color: t.focus),
                    maxLines: 1,
                  ),
                ),
                SizedBox(height: t.s2),
                Text(
                  game.installed
                      ? '> ${game.routeDisplay.toUpperCase()} // v${game.version}'
                      : '> NOT INSTALLED // ${routeName(game.route).toUpperCase()}',
                  style: t.title.copyWith(color: const Color(0xFFF2F2EC)),
                  overflow: TextOverflow.ellipsis,
                ),
                SizedBox(height: t.s2),
                Wrap(
                  spacing: t.s2,
                  runSpacing: t.s1,
                  children: [
                    for (final tag in game.tags)
                      Tag(
                        tag,
                        fill: const Color(0xFF000000),
                        fg: const Color(0xFFF2F2EC),
                      ),
                  ],
                ),
              ],
            ),
          ),
          SizedBox(width: t.s4),
          Column(
            mainAxisAlignment: MainAxisAlignment.center,
            crossAxisAlignment: CrossAxisAlignment.end,
            children: [
              Sticker(
                busy ? 'Working' : (game.installed ? 'Active' : 'Off'),
                color: busy ? t.primary : (game.installed ? t.ok : t.focus),
                fg: busy || game.installed ? Colors.white : t.onFocus,
                display: true,
              ),
              SizedBox(height: t.s4),
              const Row(
                mainAxisSize: MainAxisSize.min,
                children: [
                  KeyGlyph('A', filled: true),
                  SizedBox(width: 8),
                  Text(
                    'CONFIGURE',
                    style: TextStyle(
                      color: Color(0xFFF2F2EC),
                      fontFamily: brutalMono,
                      fontWeight: FontWeight.w600,
                    ),
                  ),
                ],
              ),
            ],
          ),
        ],
      ),
    );
  }
}

// ---- ENGINE ----------------------------------------------------------------

class _EnginePage extends StatelessWidget {
  const _EnginePage({required this.model});
  final AppModel model;

  @override
  Widget build(BuildContext context) {
    final t = context.brutal;
    final m = model;
    final c = m.core;
    return PadListener(
      onAction: (a) {
        if (a == PadAction.y && !m.building) m.rescan();
      },
      child: Padding(
        padding: EdgeInsets.all(t.s6),
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Expanded(
              flex: 5,
              child: SingleChildScrollView(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    Row(
                      children: [
                        Text('CORE', style: t.displaySmall),
                        SizedBox(width: t.s4),
                        if (c != null)
                          Sticker(
                            c.weightsBuilt ? 'Built' : 'Not built',
                            color: c.weightsBuilt ? t.ok : t.danger,
                            fg: Colors.white,
                            display: true,
                          ),
                      ],
                    ),
                    SizedBox(height: t.s3),
                    if (c != null)
                      KeyValueStrip([
                        ('Core', 'HelixSR ${c.version}'),
                        (
                          'Network',
                          c.networkEmbedded
                              ? 'embedded'
                              : (c.networkSeparate
                                    ? 'separate files'
                                    : 'not built'),
                        ),
                        ('DLL', formatBytes(c.dllSize)),
                        ('Python', c.hasPython ? 'found' : 'missing'),
                        ('GPU', m.gpus.isEmpty ? '...' : m.gpus.first.name),
                      ]),
                    SizedBox(height: t.s6),
                    ConsoleRow(
                      label: m.building
                          ? 'Building network...'
                          : 'Build network',
                      sub: 'compile DLSS Model E locally into the core DLL',
                      icon: PixelGlyph.bolt,
                      primary: true,
                      autofocus: true,
                      onPressed: m.building ? null : () => m.build(),
                    ),
                    SizedBox(height: t.s3),
                    ConsoleRow(
                      label: 'Sync games',
                      sub: 'copy the core DLL into every installed game',
                      icon: PixelGlyph.refresh,
                      onPressed: m.building ? null : m.syncInstalled,
                    ),
                  ],
                ),
              ),
            ),
            SizedBox(width: t.s6),
            Expanded(
              flex: 6,
              child: Padding(
                padding: EdgeInsets.only(
                  right: t.shadowOffsetLarge.dx,
                  bottom: t.shadowOffsetLarge.dy,
                ),
                child: Container(
                  decoration: BoxDecoration(
                    color: const Color(0xFF000000),
                    border: Border.all(color: t.ink, width: t.border),
                    boxShadow: [
                      BoxShadow(color: t.shadow, offset: t.shadowOffsetLarge),
                    ],
                  ),
                  padding: EdgeInsets.all(t.s3),
                  child: ListView(
                    reverse: true,
                    children: [
                      for (final l
                          in (m.buildLog.isEmpty
                                  ? ['> compiler output appears here']
                                  : m.buildLog)
                              .reversed)
                        Text(
                          l,
                          style: t.small.copyWith(
                            color: const Color(0xFFF2F2EC),
                          ),
                        ),
                    ],
                  ),
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

// ---- SYSTEM ----------------------------------------------------------------

class _SystemPage extends StatelessWidget {
  const _SystemPage({required this.model});
  final AppModel model;

  static T cycle<T>(List<T> v, T cur, int dir) =>
      v[(v.indexOf(cur) + dir + v.length) % v.length];

  @override
  Widget build(BuildContext context) {
    final t = context.brutal;
    final m = model;
    final s = m.settings;
    return Padding(
      padding: EdgeInsets.all(t.s6),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Expanded(
            child: SingleChildScrollView(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  Text('SYSTEM', style: t.displaySmall),
                  SizedBox(height: t.s4),
                  ConsoleRow(
                    label: 'Desktop mode',
                    sub: 'mouse and keyboard layout',
                    icon: PixelGlyph.monitor,
                    autofocus: true,
                    onPressed: () {
                      m.update((x) => x.uiMode = 'desktop');
                      m.setConsoleMode(false);
                    },
                  ),
                  SizedBox(height: t.s3),
                  ConsoleRow(
                    label: 'Interface',
                    value: s.uiMode,
                    onStep: (d) => m.update(
                      (x) => x.uiMode = cycle(
                        const ['auto', 'desktop', 'console'],
                        x.uiMode,
                        d,
                      ),
                    ),
                  ),
                  SizedBox(height: t.s3),
                  ConsoleRow(
                    label: 'Theme',
                    value: s.theme,
                    onStep: (d) => m.update(
                      (x) => x.theme = cycle(
                        const ['paper', 'ink', 'system'],
                        x.theme,
                        d,
                      ),
                    ),
                  ),
                  SizedBox(height: t.s3),
                  ConsoleRow(
                    label: 'Accent',
                    value: s.accent,
                    onStep: (d) => m.update(
                      (x) => x.accent = cycle(
                        const ['hazard', 'gold'],
                        x.accent,
                        d,
                      ),
                    ),
                  ),
                  SizedBox(height: t.s3),
                  ConsoleRow(
                    label: 'Rescan library',
                    icon: PixelGlyph.refresh,
                    onPressed: m.scanning ? null : m.rescan,
                  ),
                ],
              ),
            ),
          ),
          SizedBox(width: t.s6),
          Expanded(
            child: SingleChildScrollView(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  Text('FOLDERS', style: t.displaySmall),
                  SizedBox(height: t.s4),
                  ConsoleRow(
                    label: 'Add folder',
                    sub: 'Steam libraries are found automatically',
                    icon: PixelGlyph.plus,
                    primary: true,
                    onPressed: () => pickFolderConsole(context, m),
                  ),
                  for (final f in s.customFolders) ...[
                    SizedBox(height: t.s3),
                    _FolderRow(path: f, onRemove: () => m.removeFolder(f)),
                  ],
                  SizedBox(height: t.s6),
                  Text(
                    '> HelixSR Manager v$appVersion // core v$coreVersion\n> ${m.handheld.isHandheld ? m.handheld.device : 'desktop'}'
                    '${m.handheld.reason.isEmpty ? '' : ' // ${m.handheld.reason}'}',
                    style: t.small.copyWith(color: t.mutedText),
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

class _FolderRow extends StatelessWidget {
  const _FolderRow({required this.path, required this.onRemove});
  final String path;
  final VoidCallback onRemove;

  @override
  Widget build(BuildContext context) {
    final t = context.brutal;
    return Row(
      children: [
        Expanded(
          child: Container(
            height: t.buttonHeight,
            alignment: Alignment.centerLeft,
            padding: EdgeInsets.symmetric(horizontal: t.s3),
            decoration: BoxDecoration(
              color: t.panel,
              border: Border.all(color: t.ink, width: t.borderThin),
            ),
            child: Text(path, style: t.small, overflow: TextOverflow.ellipsis),
          ),
        ),
        SizedBox(width: t.s3),
        SizedBox(
          width: 220 * t.scale,
          child: HoldToConfirm(
            label: 'Hold to remove',
            icon: PixelGlyph.cross,
            onConfirmed: onRemove,
          ),
        ),
      ],
    );
  }
}
