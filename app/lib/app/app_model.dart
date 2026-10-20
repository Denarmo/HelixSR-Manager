/// The one ChangeNotifier behind both shells: library, filters, selection,
/// per-game actions, engine build and persisted settings.
library;

import 'package:flutter/foundation.dart';

import '../engine/engine.dart';
import 'engine_api.dart';

enum GameFilter { all, installed, notInstalled, dlss, reEngine }

enum SortKey { title, status, route, version }

class AppModel extends ChangeNotifier {
  AppModel({EngineApi? engine, Settings? settings, this.args = const []})
    : engine = engine ?? const IsolateEngine(),
      settings = settings ?? Settings.load();

  final EngineApi engine;
  final Settings settings;
  final List<String> args;

  List<GameInfo> games = [];
  CoreStatus? core;
  List<GpuInfo> gpus = const [];
  HandheldInfo handheld = const HandheldInfo();

  bool scanning = false;
  bool building = false;
  final Set<String> busy = {};

  /// Newest last. Shared activity log shown on the library and engine pages.
  final List<String> activity = [];
  final List<String> buildLog = [];

  String query = '';
  GameFilter filter = GameFilter.all;
  SortKey sortKey = SortKey.title;
  bool sortAscending = true;

  GameInfo? selected;

  /// Set when the pad/keyboard user switches mode by hand this session.
  bool? _consoleOverride;

  bool get consoleMode {
    if (_consoleOverride != null) return _consoleOverride!;
    switch (settings.uiMode) {
      case 'console':
        return true;
      case 'desktop':
        return false;
    }
    return handheld.isHandheld;
  }

  void setConsoleMode(bool on) {
    _consoleOverride = on;
    notifyListeners();
  }

  void toggleConsoleMode() => setConsoleMode(!consoleMode);

  Future<void> init() async {
    handheld = detectHandheldEnvironment(args);
    notifyListeners();
    core = await engine.coreStatus();
    notifyListeners();
    await rescan();
    gpus = await engine.gpus();
    notifyListeners();
  }

  void log(String line) {
    activity.add(line);
    if (activity.length > 200) activity.removeAt(0);
  }

  Future<void> rescan() async {
    scanning = true;
    notifyListeners();
    try {
      games = await engine.scan(settings.customFolders);
      core = await engine.coreStatus();
      if (selected != null) {
        selected = games.where((g) => g.id == selected!.id).firstOrNull;
      }
      log('scan complete ... ok (${games.length} games)');
    } catch (e) {
      log('scan error: $e');
    } finally {
      scanning = false;
      notifyListeners();
    }
  }

  // ---- list view ---------------------------------------------------------

  List<GameInfo> get visible {
    final q = query.trim().toLowerCase();
    final out = games.where((g) {
      if (q.isNotEmpty &&
          !g.name.toLowerCase().contains(q) &&
          !g.folder.toLowerCase().contains(q)) {
        return false;
      }
      switch (filter) {
        case GameFilter.all:
          return true;
        case GameFilter.installed:
          return g.installed;
        case GameFilter.notInstalled:
          return !g.installed;
        case GameFilter.dlss:
          return g.inputs.contains('DLSS');
        case GameFilter.reEngine:
          return g.isReEngine;
      }
    }).toList();
    int cmp(GameInfo a, GameInfo b) {
      switch (sortKey) {
        case SortKey.title:
          return a.name.toLowerCase().compareTo(b.name.toLowerCase());
        case SortKey.status:
          return (b.installed ? 1 : 0) - (a.installed ? 1 : 0);
        case SortKey.route:
          return a.route.compareTo(b.route);
        case SortKey.version:
          return a.version.compareTo(b.version);
      }
    }

    out.sort(sortAscending ? cmp : (a, b) => cmp(b, a));
    return out;
  }

  int count(GameFilter f) {
    switch (f) {
      case GameFilter.all:
        return games.length;
      case GameFilter.installed:
        return games.where((g) => g.installed).length;
      case GameFilter.notInstalled:
        return games.where((g) => !g.installed).length;
      case GameFilter.dlss:
        return games.where((g) => g.inputs.contains('DLSS')).length;
      case GameFilter.reEngine:
        return games.where((g) => g.isReEngine).length;
    }
  }

  void setQuery(String q) {
    query = q;
    notifyListeners();
  }

  void setFilter(GameFilter f) {
    filter = f;
    notifyListeners();
  }

  void sortBy(SortKey k) {
    if (sortKey == k) {
      sortAscending = !sortAscending;
    } else {
      sortKey = k;
      sortAscending = true;
    }
    notifyListeners();
  }

  void select(GameInfo? g) {
    selected = g;
    notifyListeners();
  }

  /// Option edits on a game (route, proxy DLL...) that notify the UI.
  void edit(GameInfo g, void Function(GameInfo g) change) {
    change(g);
    notifyListeners();
  }

  // ---- actions -----------------------------------------------------------

  bool isBusy(GameInfo g) => busy.contains(g.id);

  void _replace(GameInfo old, GameInfo fresh) {
    final i = games.indexWhere((g) => g.id == old.id);
    if (i >= 0) games[i] = fresh;
    if (selected?.id == old.id) selected = fresh;
  }

  /// Returns an error message or null.
  Future<String?> install(GameInfo g) async {
    if (isBusy(g)) return null;
    busy.add(g.id);
    log('install ${g.name} [${g.routeDisplay}]');
    notifyListeners();
    try {
      final (fresh, lines) = await engine.install(g);
      for (final l in lines) {
        log('  $l');
      }
      _replace(g, fresh);
      log('install ${g.name} ... ok');
      return null;
    } catch (e) {
      log('install ${g.name} error: $e');
      return '$e';
    } finally {
      busy.remove(g.id);
      notifyListeners();
    }
  }

  Future<String?> uninstall(GameInfo g) async {
    if (isBusy(g)) return null;
    busy.add(g.id);
    log('uninstall ${g.name}');
    notifyListeners();
    try {
      _replace(g, await engine.uninstall(g));
      log('uninstall ${g.name} ... ok');
      return null;
    } catch (e) {
      log('uninstall ${g.name} error: $e');
      return '$e';
    } finally {
      busy.remove(g.id);
      notifyListeners();
    }
  }

  Future<void> build({String dlssPath = ''}) async {
    if (building) return;
    building = true;
    buildLog.clear();
    notifyListeners();
    try {
      await engine.buildNetwork(
        dlssPath: dlssPath,
        log: (l) {
          buildLog.add(l);
          if (buildLog.length > 800) buildLog.removeAt(0);
          notifyListeners();
        },
        games: () => games,
      );
    } finally {
      building = false;
      core = await engine.coreStatus();
      notifyListeners();
      await rescan();
    }
  }

  Future<int> syncInstalled() async {
    final n = await engine.sync(games.where((g) => g.installed).toList());
    log('sync ... ok ($n updated)');
    notifyListeners();
    await rescan();
    return n;
  }

  Future<void> addFolder(String path) async {
    final norm = normalizePath(path);
    if (norm.isEmpty || settings.customFolders.contains(norm)) return;
    settings.customFolders.add(norm);
    settings.save();
    await rescan();
  }

  Future<void> removeFolder(String path) async {
    settings.customFolders.remove(path);
    settings.save();
    await rescan();
  }

  // ---- appearance --------------------------------------------------------

  void update(void Function(Settings s) change) {
    change(settings);
    settings.save();
    notifyListeners();
  }
}
