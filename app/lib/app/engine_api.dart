/// What the UI needs from the engine. The default implementation runs the
/// blocking file work in a background isolate; tests substitute a fake.
library;

import 'dart:isolate';

import '../engine/engine.dart';
import '../engine/steam.dart' as steam;

abstract class EngineApi {
  Future<List<GameInfo>> scan(List<String> customFolders);

  /// Installs with the route and options set on [game]; returns the game as
  /// scanned afterwards plus the engine's progress lines.
  Future<(GameInfo, List<String>)> install(GameInfo game);

  Future<GameInfo> uninstall(GameInfo game);

  Future<CoreStatus> coreStatus();

  Future<List<GpuInfo>> gpus();

  /// Refreshes HelixSR in every installed game; returns how many changed.
  Future<int> sync(List<GameInfo> games);

  /// Streams the network compiler output; returns games updated, -1 on error.
  Future<int> buildNetwork({
    required String dlssPath,
    required void Function(String) log,
    required List<GameInfo> Function() games,
  });
}

class IsolateEngine implements EngineApi {
  const IsolateEngine();

  @override
  Future<List<GameInfo>> scan(List<String> customFolders) =>
      Isolate.run(() => scanAllGames(customFolders));

  @override
  Future<(GameInfo, List<String>)> install(GameInfo game) =>
      Isolate.run(() async {
        final lines = <String>[];
        await installHelixSr(game, log: lines.add);
        return (_rescan(game), lines);
      });

  @override
  Future<GameInfo> uninstall(GameInfo game) => Isolate.run(() {
    uninstallHelixSr(game);
    return _rescan(game);
  });

  @override
  Future<CoreStatus> coreStatus() => Isolate.run(() => Core.instance.status());

  @override
  Future<List<GpuInfo>> gpus() => getGpuInfo();

  @override
  Future<int> sync(List<GameInfo> games) =>
      Isolate.run(() => syncHelixSrToInstalledGames(games));

  @override
  Future<int> buildNetwork({
    required String dlssPath,
    required void Function(String) log,
    required List<GameInfo> Function() games,
  }) => buildNetworkProcess(dlssPath: dlssPath, log: log, games: games);
}

GameInfo _rescan(GameInfo g) =>
    scanGame(g.folder, g.name, steam.getSteamManifests());

/// The compiler runs as a child process, so it stays on the UI isolate (its
/// output is a stream, not blocking work).
Future<int> buildNetworkProcess({
  required String dlssPath,
  required void Function(String) log,
  required List<GameInfo> Function() games,
}) => buildNetwork(dlssPath: dlssPath, log: log, installedGames: games);
