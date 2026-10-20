/// Games: filters | table (or poster grid) | INSPECT. On narrow windows the
/// inspector opens as its own page.
library;

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../../app/app_model.dart';
import '../../app/pickers.dart';
import '../../engine/engine.dart';
import '../brutal/brutal.dart';
import '../common/game_cover.dart';
import 'inspector.dart';

class LibraryPage extends StatefulWidget {
  const LibraryPage({super.key, required this.model});
  final AppModel model;

  @override
  State<LibraryPage> createState() => _LibraryPageState();
}

class _LibraryPageState extends State<LibraryPage> {
  final search = TextEditingController();
  final searchNode = FocusNode();

  AppModel get m => widget.model;

  @override
  void dispose() {
    search.dispose();
    searchNode.dispose();
    super.dispose();
  }

  Future<void> addFolder() async {
    final dir = await Pickers.directory();
    if (dir != null) await m.addFolder(dir);
  }

  void open(GameInfo g) {
    m.select(g);
    if (MediaQuery.sizeOf(context).width < _wide) {
      Navigator.of(context).push(
        MaterialPageRoute<void>(builder: (_) => _InspectorRoute(model: m)),
      );
    }
  }

  static const double _wide = 1180;

  @override
  Widget build(BuildContext context) {
    final t = context.brutal;
    return ListenableBuilder(
      listenable: m,
      builder: (context, _) {
        final wide = MediaQuery.sizeOf(context).width >= _wide;
        final games = m.visible;
        final grid = m.settings.libraryView == 'grid';
        final list = games.isEmpty && !m.scanning
            ? EmptyState(
                headline: m.games.isEmpty ? 'No games found.' : 'No match.',
                body: m.games.isEmpty
                    ? 'add a folder to start'
                    : 'clear the filter or search',
                actions: [
                  BrutalButton(
                    label: 'Add folder',
                    icon: PixelGlyph.folder,
                    variant: ButtonVariant.primary,
                    onPressed: addFolder,
                  ),
                ],
              )
            : grid
            ? _PosterGrid(games: games, selected: m.selected, onOpen: open)
            : _GameTable(model: m, games: games, onOpen: open);
        return CallbackShortcuts(
          bindings: {
            const SingleActivator(LogicalKeyboardKey.slash):
                searchNode.requestFocus,
          },
          child: Padding(
            padding: EdgeInsets.all(t.s4),
            child: Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                SizedBox(
                  width: 248 * t.scale,
                  child: _FilterRail(
                    model: m,
                    search: search,
                    searchNode: searchNode,
                    onAdd: addFolder,
                  ),
                ),
                SizedBox(width: t.s4 + t.shadowOffsetLarge.dx),
                Expanded(
                  child: Padding(
                    padding: EdgeInsets.only(
                      right: t.shadowOffsetLarge.dx,
                      bottom: t.shadowOffsetLarge.dy,
                    ),
                    child: list,
                  ),
                ),
                if (wide) ...[
                  SizedBox(width: t.s4),
                  SizedBox(
                    width: 440 * t.scale,
                    child: m.selected == null
                        ? BrutalPanel(
                            header: 'Inspect',
                            child: Text('> select a game', style: t.body),
                          )
                        : Inspector(
                            key: ValueKey(m.selected!.id),
                            model: m,
                            game: m.selected!,
                          ),
                  ),
                ],
              ],
            ),
          ),
        );
      },
    );
  }
}

class _FilterRail extends StatelessWidget {
  const _FilterRail({
    required this.model,
    required this.search,
    required this.searchNode,
    required this.onAdd,
  });
  final AppModel model;
  final TextEditingController search;
  final FocusNode searchNode;
  final VoidCallback onAdd;

  @override
  Widget build(BuildContext context) {
    final t = context.brutal;
    final m = model;
    return SingleChildScrollView(
      child: Padding(
        padding: EdgeInsets.only(
          right: t.shadowOffset.dx,
          bottom: t.shadowOffset.dy,
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            CommandField(
              controller: search,
              focusNode: searchNode,
              onChanged: m.setQuery,
              onSubmitted: (_) => FocusScope.of(context).nextFocus(),
            ),
            SizedBox(height: t.s4),
            BrutalPanel(
              header: 'Filter',
              padding: EdgeInsets.symmetric(vertical: t.s2, horizontal: t.s1),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  for (final (f, name) in [
                    (GameFilter.all, 'All'),
                    (GameFilter.installed, 'Active'),
                    (GameFilter.notInstalled, 'Not installed'),
                    (GameFilter.dlss, 'DLSS'),
                    (GameFilter.reEngine, 'RE Engine'),
                  ])
                    CheckFilter(
                      label: name,
                      count: m.count(f),
                      checked: m.filter == f,
                      onPressed: () => m.setFilter(f),
                    ),
                ],
              ),
            ),
            SizedBox(height: t.s4),
            BrutalPanel(
              header: 'View',
              child: CfgSegment<String>(
                options: const ['table', 'grid'],
                value: m.settings.libraryView,
                labelOf: (v) => v,
                onChanged: (v) => m.update((s) => s.libraryView = v),
              ),
            ),
            SizedBox(height: t.s4),
            BrutalButton(
              label: 'Add folder',
              icon: PixelGlyph.folder,
              expand: true,
              onPressed: onAdd,
            ),
            SizedBox(height: t.s3),
            BrutalButton(
              label: m.scanning ? 'Scanning' : 'Rescan',
              icon: PixelGlyph.refresh,
              expand: true,
              onPressed: m.scanning ? null : m.rescan,
            ),
            SizedBox(height: t.s4),
            if (m.activity.isNotEmpty)
              Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  for (final l in m.activity.reversed.take(4).toList().reversed)
                    LogLine(l),
                ],
              ),
          ],
        ),
      ),
    );
  }
}

class _GameTable extends StatelessWidget {
  const _GameTable({
    required this.model,
    required this.games,
    required this.onOpen,
  });
  final AppModel model;
  final List<GameInfo> games;
  final ValueChanged<GameInfo> onOpen;

  @override
  Widget build(BuildContext context) {
    final t = context.brutal;
    final m = model;
    return BrutalTable<GameInfo>(
      items: games,
      selected: m.selected,
      autofocusFirst: false,
      onActivate: onOpen,
      onSecondary: onOpen,
      onFocusItem: (g) {
        // The inspector follows focus on the wide layout.
        if (MediaQuery.sizeOf(context).width >= 1180 &&
            m.selected?.id != g.id) {
          WidgetsBinding.instance.addPostFrameCallback((_) => m.select(g));
        }
      },
      sortKey: m.sortKey.name,
      sortAscending: m.sortAscending,
      onSort: (k) => m.sortBy(SortKey.values.firstWhere((e) => e.name == k)),
      columns: const [
        BrutalColumn('#', width: 48),
        BrutalColumn('Box', width: 56),
        BrutalColumn('Title', flex: 4, sortKey: 'title'),
        BrutalColumn('Status', width: 132, sortKey: 'status'),
        BrutalColumn('Route', flex: 3, sortKey: 'route'),
        BrutalColumn('Inputs', flex: 3),
        BrutalColumn(
          'Ver',
          width: 64,
          sortKey: 'version',
          align: TextAlign.right,
        ),
      ],
      cellBuilder: (context, g, i, col) {
        switch (col) {
          case 0:
            return Text('${i + 1}'.padLeft(2, '0'));
          case 1:
            return SizedBox(
              width: 26 * t.scale,
              height: t.rowHeight - 10 * t.scale,
              child: GameCover(g, border: true),
            );
          case 2:
            return Text(
              BrutalTokens.fileName(g.name),
              overflow: TextOverflow.ellipsis,
            );
          case 3:
            return m.isBusy(g)
                ? const Text('WORKING...')
                : Text(g.installed ? '[x] ACTIVE' : '[ ] OFF');
          case 4:
            return Text(
              g.installed ? g.routeDisplay.toUpperCase() : '---',
              overflow: TextOverflow.ellipsis,
            );
          case 5:
            return Text(
              g.tags.isEmpty ? '---' : g.tags.join(' '),
              overflow: TextOverflow.ellipsis,
            );
          default:
            return Text(g.installed ? g.version : '--');
        }
      },
    );
  }
}

class _PosterGrid extends StatelessWidget {
  const _PosterGrid({
    required this.games,
    required this.selected,
    required this.onOpen,
  });
  final List<GameInfo> games;
  final GameInfo? selected;
  final ValueChanged<GameInfo> onOpen;

  @override
  Widget build(BuildContext context) {
    final t = context.brutal;
    return GridView.builder(
      padding: EdgeInsets.all(t.s2),
      gridDelegate: SliverGridDelegateWithMaxCrossAxisExtent(
        maxCrossAxisExtent: 190 * t.scale,
        childAspectRatio: 0.58,
        crossAxisSpacing: t.s4,
        mainAxisSpacing: t.s4,
      ),
      itemCount: games.length,
      itemBuilder: (context, i) {
        final g = games[i];
        return Pressable(
          onPressed: () => onOpen(g),
          builder: (c, st) {
            final hot = st.active || selected?.id == g.id;
            return Container(
              decoration: BoxDecoration(
                color: hot ? t.focus : t.panel,
                border: Border.all(color: t.ink, width: t.border),
                boxShadow: [BoxShadow(color: t.shadow, offset: t.shadowOffset)],
              ),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  Expanded(child: GameCover(g, border: false)),
                  Container(
                    padding: EdgeInsets.all(t.s2),
                    decoration: BoxDecoration(
                      border: Border(
                        top: BorderSide(color: t.ink, width: t.border),
                      ),
                    ),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(
                          BrutalTokens.fileName(g.name),
                          maxLines: 1,
                          overflow: TextOverflow.ellipsis,
                          style: t.label.copyWith(
                            color: hot ? t.onFocus : t.ink,
                          ),
                        ),
                        Text(
                          g.installed ? '[x] ${g.version}' : '[ ] OFF',
                          style: t.small.copyWith(
                            color: hot ? t.onFocus : t.mutedText,
                          ),
                        ),
                      ],
                    ),
                  ),
                ],
              ),
            );
          },
        );
      },
    );
  }
}

class _InspectorRoute extends StatelessWidget {
  const _InspectorRoute({required this.model});
  final AppModel model;

  @override
  Widget build(BuildContext context) {
    final t = context.brutal;
    return Scaffold(
      body: GridPaper8(
        child: SafeArea(
          child: ListenableBuilder(
            listenable: model,
            builder: (context, _) {
              final g = model.selected;
              return Padding(
                padding: EdgeInsets.all(t.s4),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    Align(
                      alignment: Alignment.centerLeft,
                      child: BrutalButton(
                        label: 'Back',
                        icon: PixelGlyph.arrowLeft,
                        autofocus: true,
                        onPressed: () => Navigator.of(context).pop(),
                      ),
                    ),
                    SizedBox(height: t.s4),
                    Expanded(
                      child: g == null
                          ? const SizedBox.shrink()
                          : Inspector(
                              key: ValueKey(g.id),
                              model: model,
                              game: g,
                            ),
                    ),
                  ],
                ),
              );
            },
          ),
        ),
      ),
    );
  }
}
