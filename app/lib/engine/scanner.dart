/// Game discovery: walks a game folder (depth 6) for upscaler DLLs, the real
/// executable folder and existing HelixSR installs.
library;

import 'dart:convert';
import 'dart:io';

import 'package:path/path.dart' as p;

import 'constants.dart';
import 'models.dart';
import 'paths.dart';
import 'steam.dart';

String _gameId(String folder) =>
    base64.encode(utf8.encode(folder)).replaceAll('=', '');

Map<String, dynamic>? _readJson(String path) {
  try {
    final v = jsonDecode(readText(path));
    return v is Map<String, dynamic> ? v : null;
  } catch (_) {
    return null;
  }
}

GameInfo scanGame(
  String gameFolder,
  String? fallbackName,
  Map<String, ManifestInfo>? manifests,
) {
  gameFolder = normalizePath(gameFolder);
  final folderName = p.basename(gameFolder);
  final manifest = manifests?[folderName.toLowerCase()];

  final game = GameInfo(
    id: _gameId(gameFolder),
    name: manifest?.name ?? fallbackName ?? folderName,
    folder: gameFolder,
    appId: manifest?.appId,
    launcher: manifest != null ? 'Steam' : 'Custom',
  );

  if (game.appId != null) {
    game.localCoverPath = findSteamArtwork(game.appId);
    game.localHeroPath = findSteamArtwork(game.appId, hero: true);
    game.remoteCoverUrl = steamArtUrl(game.appId!);
    game.remoteHeroUrl = steamArtUrl(game.appId!, hero: true);
  }

  _processGameDirectory(game, gameFolder);

  final (opti, dlss) = _checkOptiScalerRoute(game);
  final direct = _checkDirectRoute(game);

  if (dlss) {
    game.route = 'dlss';
    game.installed = true;
  } else if (opti) {
    game.route = 'optiscaler';
    game.installed = true;
  } else if (direct) {
    game.route = 'direct';
    game.installed = true;
  } else {
    game.route = 'optiscaler';
    game.optiDllName = 'dxgi.dll';
  }
  return game;
}

class _Walk {
  final inputs = <String>{};
  final fsrTargets = <String>[];
  String? bestExeDir;
  int bestExeSize = -1;
  String? bestExeName;
}

void _processGameDirectory(GameInfo game, String gameFolder) {
  final w = _Walk();
  _scanDir(gameFolder, 0, 6, w, game);

  if (w.bestExeDir == null && game.foundNvngxDlssPath != null) {
    w.bestExeDir = p.dirname(game.foundNvngxDlssPath!);
  }
  // In Capcom RE Engine / REFramework, _storage_ is an engine directory;
  // the executable lives in the parent.
  if (w.bestExeDir != null &&
      p.basename(w.bestExeDir!).toLowerCase() == '_storage_') {
    w.bestExeDir = gameFolder;
  }

  game.exeFolder = w.bestExeDir ?? gameFolder;
  game.exeName = w.bestExeName;
  game.inputs = w.inputs.toList();
  game.fsrTargets = w.fsrTargets;
  game.isReEngine = detectReEngine(gameFolder, game);
  game.isInZoi = detectInZoi(gameFolder, game);
  game.installReFramework =
      game.isReEngine ||
      fileExists(
        p.join(game.exeFolder ?? gameFolder, 'reframework_revision.txt'),
      );
}

const int _huge = 1 << 60;

void _scanDir(String dir, int depth, int maxDepth, _Walk w, GameInfo game) {
  if (depth > maxDepth || !dirExists(dir)) return;
  try {
    final entries = Directory(dir).listSync(followLinks: false);
    final files = entries.whereType<File>().toList();

    var hasOptiMarker = false;
    for (final f in files) {
      if (p.basename(f.path).toLowerCase() == 'optiscaler.ini') {
        hasOptiMarker = true;
        w.bestExeDir = dir;
        w.bestExeSize = _huge;
      }
    }
    // A folder with a HelixSR install record wins, as upstream.
    if (!hasOptiMarker && fileExists(p.join(dir, helixSrFolder, markerFile))) {
      hasOptiMarker = true;
      w.bestExeDir = dir;
      w.bestExeSize = _huge;
    }

    for (final f in files) {
      final name = p.basename(f.path);
      final lower = name.toLowerCase();
      switch (lower) {
        case 'nvngx_dlss.dll':
          w.inputs.add('DLSS');
          final old = game.foundNvngxDlssPath;
          // Prefer the larger DLSS DLL (root game vs SP/MP subfolder).
          if (old == null || fileSize(f.path) > fileSize(old)) {
            game.foundNvngxDlssPath = f.path;
          }
        case 'nvngx_dlssg.dll' || 'sl.dlss_g.dll':
          w.inputs.add('DLSS-G');
          game.hasDlssG = true;
        case 'libxess.dll':
          w.inputs.add('XeSS');
        case 'libxess_fg.dll':
          game.foundXeFgPath = f.path;
        case 'libxell.dll':
          game.foundXeLlPath = f.path;
        case 'amd_fidelityfx_framegeneration_dx12.dll':
          game.foundFfxFgPath = f.path;
        case 'ffx_fsr2_api_x64.dll' || 'ffx_fsr2_api_dx12_x64.dll':
          w.inputs.add('FSR 2');
        default:
          if (lower == dllSr || lower == dllFsr) w.fsrTargets.add(f.path);
      }

      if (lower.endsWith('.exe') && !skipExe.hasMatch(name)) {
        var sz = fileSize(f.path);
        if (lower.endsWith('-win64-shipping.exe')) sz += 1000000000000;
        if (!hasOptiMarker && sz > w.bestExeSize) {
          w.bestExeSize = sz;
          w.bestExeDir = dir;
          w.bestExeName = name;
        }
      }
    }

    if (depth < maxDepth) {
      for (final d in entries.whereType<Directory>()) {
        if (p.basename(d.path).toLowerCase() != helixSrFolder.toLowerCase()) {
          _scanDir(d.path, depth + 1, maxDepth, w, game);
        }
      }
    }
  } catch (_) {}
}

/// (optiscaler route installed, dlss loader route installed)
(bool, bool) _checkOptiScalerRoute(GameInfo game) {
  var opti = false;
  var dlss = false;
  final exe = game.exeFolder;
  if (exe == null || exe.isEmpty) return (false, false);
  final helixDir = p.join(exe, helixSrFolder);
  final marker = p.join(helixDir, markerFile);
  if (fileExists(marker)) {
    opti = true;
    final data = _readJson(marker);
    if (data != null) {
      if (data['helixsr'] != null) game.version = '${data['helixsr']}';
      if (data['optiscaler'] != null)
        game.optiDllName = '${data['optiscaler']}';
      if (data['fakenvapi'] is bool)
        game.useFakeNvapi = data['fakenvapi'] as bool;
      if (data['fg_mode'] != null) game.fgMode = '${data['fg_mode']}';
      if (data['route'] == 'dlss') {
        dlss = true;
        opti = false;
      }
    }
  }
  final backup = Directory(p.join(helixDir, backupFolder));
  try {
    if (backup.existsSync() && backup.listSync().whereType<File>().isNotEmpty) {
      game.hasBackups = true;
    }
  } catch (_) {}
  if (fileExists(p.join(helixDir, 'helixsr.log')) ||
      fileExists(p.join(exe, 'OptiScaler.log')) ||
      fileExists(p.join(exe, 'helixsr.log')) ||
      fileExists(p.join(exe, 'helixsr_loader.log'))) {
    game.hasLogs = true;
  }
  if (dirExists(p.join(helixDir, myFsrFolder))) game.hasMyFsr = true;
  return (opti, dlss);
}

bool _checkDirectRoute(GameInfo game) {
  var direct = false;
  for (final target in game.fsrTargets) {
    final orig = originalName(target);
    final marker = p.join(p.dirname(target), markerFile);
    if (fileExists(orig) || fileExists(marker)) {
      direct = true;
      game.hasBackups = game.hasBackups || fileExists(orig);
      final data = _readJson(marker);
      if (data?['helixsr'] != null) game.version = '${data!['helixsr']}';
      if (fileExists(p.join(p.dirname(target), 'helixsr.log')))
        game.hasLogs = true;
    }
  }
  final exe = game.exeFolder;
  if (!direct && exe != null && exe.isNotEmpty) {
    final exeMarker = p.join(exe, markerFile);
    if (fileExists(exeMarker)) {
      direct = true;
      final data = _readJson(exeMarker);
      if (data?['helixsr'] != null) game.version = '${data!['helixsr']}';
    }
  }
  return direct;
}

/// foo.dll -> foo.original.dll
String originalName(String dllPath) => p.join(
  p.dirname(dllPath),
  '${p.basenameWithoutExtension(dllPath)}.original.dll',
);

bool detectReEngine(String gameFolder, GameInfo? game) {
  if (!dirExists(gameFolder)) return false;
  // Pragmata, Monster Hunter Wilds, Dragon's Dogma 2 layouts.
  if (dirExists(p.join(gameFolder, '_storage_'))) return true;
  try {
    final chunk = RegExp(r'^re_chunk_.*\.pak$', caseSensitive: false);
    for (final f in Directory(gameFolder).listSync().whereType<File>()) {
      if (chunk.hasMatch(p.basename(f.path))) return true;
    }
  } catch (_) {}
  final cfg = p.join(gameFolder, 'config.ini');
  if (fileExists(cfg)) {
    try {
      final c = readText(cfg);
      if (c.contains('[Render]') && c.contains('Capability=DirectX12'))
        return true;
    } catch (_) {}
  }
  final name =
      (game != null && game.name.isNotEmpty
              ? game.name
              : p.basename(gameFolder))
          .toLowerCase();
  return reTitles.any(name.contains);
}

bool detectInZoi(String gameFolder, GameInfo? game) {
  if (game?.appId == inZoiAppId) return true;
  if (!dirExists(gameFolder)) return false;
  if (dirExists(p.join(gameFolder, 'BlueClient', 'Binaries', 'Win64'))) {
    return true;
  }
  final exe = game?.exeName?.toLowerCase();
  if (exe != null &&
      (exe.startsWith('blueclient') || exe.startsWith('inzoi'))) {
    return true;
  }
  final name = (game != null && game.name.isNotEmpty
      ? game.name
      : p.basename(gameFolder));
  return name.toLowerCase().replaceAll(' ', '').contains('inzoi');
}

List<GameInfo> scanAllGames(List<String> customFolders) {
  final manifests = getSteamManifests();
  final result = <GameInfo>[];
  final scanned = <String>{};

  for (final lib in getSteamLibraries()) {
    final normLib = normalizePath(lib);
    if (normLib.isEmpty || !dirExists(normLib)) continue;
    try {
      for (final dir in Directory(normLib).listSync().whereType<Directory>()) {
        final norm = normalizePath(dir.path);
        final key = canonicalKey(norm);
        if (key.isEmpty || !scanned.add(key)) continue;
        final g = scanGame(norm, p.basename(norm), manifests);
        if (g.exeFolder != null) scanned.add(canonicalKey(g.exeFolder!));
        result.add(g);
      }
    } catch (_) {}
  }

  for (final folder in customFolders) {
    final norm = normalizePath(folder);
    if (norm.isEmpty || !dirExists(norm)) continue;
    final key = canonicalKey(norm);
    if (!scanned.add(key)) continue;
    final g = scanGame(norm, p.basename(norm), manifests);
    final exeKey = canonicalKey(g.exeFolder ?? '');
    if (exeKey.isNotEmpty && exeKey != key && !scanned.add(exeKey)) continue;
    result.add(g);
  }

  result.sort((a, b) => a.name.toLowerCase().compareTo(b.name.toLowerCase()));
  return result;
}
