/// Install, uninstall and sync HelixSR in a game. Port of InstallHelixSR,
/// CleanupHelixSRFiles, UninstallHelixSR and SyncHelixSRToInstalledGames in
/// src/Engine.cs; the three routes behave identically.
library;

import 'dart:convert';
import 'dart:io';

import 'package:path/path.dart' as p;

import 'constants.dart';
import 'core.dart';
import 'extras.dart';
import 'ini.dart';
import 'models.dart';
import 'paths.dart';
import 'scanner.dart';

class EngineException implements Exception {
  EngineException(this.message);
  final String message;
  @override
  String toString() => message;
}

Map<String, dynamic>? _readMarker(String path) {
  try {
    final v = jsonDecode(readText(path));
    return v is Map<String, dynamic> ? v : null;
  } catch (_) {
    return null;
  }
}

void _writeMarker(String path, Map<String, dynamic> rec) =>
    writeText(path, jsonEncode(rec));

List<String> _strings(Object? v) =>
    v is List ? v.map((e) => '$e').toList() : <String>[];

Future<void> installHelixSr(GameInfo game, {void Function(String)? log}) async {
  final core = Core.instance;
  void say(String m) => log?.call(m);

  if (!core.exists) {
    throw EngineException('HelixSR core folder missing at: ${core.dir}');
  }
  if (!core.status().weightsBuilt) {
    throw EngineException(
      "The HelixSR network has not been built yet.\nGo to ENGINE and build the HelixSR network first "
      '(HelixSR 1.8+ embeds the network into $dllFsr).',
    );
  }

  // Start clean so switching routes or proxy DLL names leaves nothing behind.
  say('cleaning previous install');
  cleanupHelixSrFiles(game);

  switch (game.route) {
    case 'optiscaler':
      _installOptiScaler(game, core, say);
    case 'direct':
      _installDirect(game, core, say);
    case 'dlss':
      _installDlssLoader(game, core, say);
  }

  if (game.isInZoi) {
    say('applying inZOI settings');
    applyInZoiUserSettings(game);
  }

  if (game.installReFramework) {
    say('installing REFramework nightly');
    await installReFrameworkNightly(game);
  } else if (fileExists(p.join(game.target, 'reframework_revision.txt'))) {
    uninstallReFramework(game);
  }
  say('done');
}

void _installOptiScaler(GameInfo game, Core core, void Function(String) say) {
  final t = game.target;
  if (!dirExists(t))
    throw EngineException('Game executable directory not found.');

  final helixDir = p.join(t, helixSrFolder);
  final backupDir = p.join(helixDir, backupFolder);
  final markerPath = p.join(helixDir, markerFile);
  Directory(backupDir).createSync(recursive: true);

  final moved = <String>[];
  final created = <String>[];
  final rec = <String, dynamic>{};

  final optiName = game.optiDllName.isNotEmpty ? game.optiDllName : 'dxgi.dll';
  final fgMode = game.fgMode.isNotEmpty ? game.fgMode : 'auto';
  if (fgMode.startsWith('dlssg_')) game.useFakeNvapi = true;
  rec['optiscaler'] = optiName;
  rec['fakenvapi'] = game.useFakeNvapi;
  rec['fg_mode'] = fgMode;

  say('hooking $optiName');
  final currentTarget = p.join(t, optiName);
  if (fileExists(currentTarget)) {
    final backupTarget = p.join(backupDir, optiName);
    if (!fileExists(backupTarget)) {
      File(currentTarget).copySync(backupTarget);
      moved.add(optiName);
    }
  }

  final gameIni = p.join(t, 'OptiScaler.ini');
  final srcIni = core.path('optiscaler', 'OptiScaler.ini');
  if (fileExists(gameIni)) {
    final backupIni = p.join(backupDir, 'OptiScaler.ini');
    if (!fileExists(backupIni)) File(gameIni).copySync(backupIni);
    rec['ini'] = 'edited';
  } else if (fileExists(srcIni)) {
    File(srcIni).copySync(gameIni);
    rec['ini'] = 'created';
  }

  // A stray fake nvapi64.dll would hijack the driver on Nvidia systems.
  tryDelete(p.join(t, 'nvapi64.dll'));

  final dstFakenvapi = p.join(t, 'fakenvapi.dll');
  final dstFakenvapiIni = p.join(t, 'fakenvapi.ini');
  if (game.useFakeNvapi) {
    final srcDll = core.path('optiscaler', 'fakenvapi.dll');
    final srcCfg = core.path('optiscaler', 'fakenvapi.ini');
    if (fileExists(srcDll)) {
      if (!fileExists(dstFakenvapi)) created.add('fakenvapi.dll');
      File(srcDll).copySync(dstFakenvapi);
    }
    if (fileExists(srcCfg)) {
      if (!fileExists(dstFakenvapiIni)) created.add('fakenvapi.ini');
      File(srcCfg).copySync(dstFakenvapiIni);
    }
  } else {
    tryDelete(dstFakenvapi);
    tryDelete(dstFakenvapiIni);
  }

  final srcOpti = core.path('optiscaler', 'OptiScaler.dll');
  if (fileExists(srcOpti)) File(srcOpti).copySync(currentTarget);

  say('copying HelixSR');
  final srcFfx = core.fsrDll;
  if (fileExists(srcFfx)) {
    File(srcFfx).copySync(p.join(helixDir, ownDll));
    File(srcFfx).copySync(p.join(helixDir, ownSrDll));
  }
  core.syncNetworkFiles(helixDir);

  final myFsrDir = p.join(helixDir, myFsrFolder);
  Directory(myFsrDir).createSync(recursive: true);
  writeText(p.join(myFsrDir, 'README.txt'), myFsrReadme);

  final srcAmdFsr = core.path('amd-fsr', dllSr);
  if (fileExists(srcAmdFsr))
    File(srcAmdFsr).copySync(p.join(helixDir, amdFsrFile));

  final coreMyFsr = core.path(myFsrFolder);
  for (final fg in [amdFgFile, 'libxess_fg.dll', 'libxell.dll']) {
    final fromGame = p.join(myFsrDir, fg);
    final fromCore = p.join(coreMyFsr, fg);
    final dst = p.join(helixDir, fg);
    if (fileExists(fromGame)) {
      File(fromGame).copySync(dst);
    } else if (fileExists(fromCore)) {
      File(fromCore).copySync(dst);
    }
  }

  // HelixSR 1.8+ ships AMD's FSR frame generation (core/amd-fsr).
  final bundledFg = core.path('amd-fsr', amdFgFile);
  final helixFg = p.join(helixDir, amdFgFile);
  if (!fileExists(helixFg) && fileExists(bundledFg))
    File(bundledFg).copySync(helixFg);

  const nukem = 'dlssg_to_fsr3_amd_is_better.dll';
  final nukemGame = p.join(myFsrDir, nukem);
  final nukemCore = p.join(coreMyFsr, nukem);
  final dstNukem = p.join(t, nukem);
  if (fileExists(nukemGame) || fileExists(nukemCore)) {
    if (!fileExists(dstNukem)) created.add(nukem);
    File(fileExists(nukemGame) ? nukemGame : nukemCore).copySync(dstNukem);
  }

  // Capcom RE Engine / REFramework: mirror into _storage_.
  final subStorage = p.join(t, '_storage_');
  if (dirExists(subStorage)) {
    final subHelix = p.join(subStorage, helixSrFolder);
    Directory(subHelix).createSync(recursive: true);
    if (fileExists(srcFfx)) {
      File(srcFfx).copySync(p.join(subHelix, ownDll));
      File(srcFfx).copySync(p.join(subHelix, ownSrDll));
    }
    core.syncNetworkFiles(subHelix);
  }

  clearShaderCache(game);

  if (fileExists(gameIni)) {
    say('configuring OptiScaler.ini');
    var text = readText(gameIni);
    text = setIniValue(text, 'Dx12Upscaler', 'fsr31', 'Upscalers');
    text = setIniValue(
      text,
      'FfxDx12Path',
      p.join(helixDir, ownDll),
      'Libraries',
    );
    text = setIniValue(
      text,
      'FfxDx12SRPath',
      p.join(helixDir, ownSrDll),
      'Libraries',
    );

    // FFX frame generation stays decoupled from the SR-only HelixSR DLL.
    text = _libraryPath(
      text,
      'FfxDx12FGPath',
      p.join(helixDir, amdFgFile),
      game.foundFfxFgPath,
    );
    text = _libraryPath(
      text,
      'XeFGPath',
      p.join(helixDir, 'libxess_fg.dll'),
      game.foundXeFgPath,
    );
    text = _libraryPath(
      text,
      'XeLLPath',
      p.join(helixDir, 'libxell.dll'),
      game.foundXeLlPath,
    );

    switch (fgMode) {
      case 'dlssg_xefg':
        text = _frameGen(text, 'true', 'dlssg', 'xefg');
      case 'dlssg_fsrfg':
        text = _frameGen(text, 'true', 'dlssg', 'fsrfg');
      case 'dlssg_nukems':
        text = _frameGen(text, 'true', 'nukems', 'nukems');
      case 'optifg_fsrfg':
        text = _frameGen(text, 'true', 'upscaler', 'fsrfg');
        text = setIniValue(text, 'HUDFix', 'true', 'OptiFG');
      default:
        text = _frameGen(text, 'auto', 'auto', 'auto');
    }

    // Everything is preconfigured: no startup splash, no update popup.
    text = setIniValue(text, 'DisableSplash', 'true', 'Menu');
    text = setIniValue(text, 'CheckForUpdate', 'false', 'Hotfix');
    if (game.isInZoi) text = applyInZoiOptiScalerIni(text);
    writeText(gameIni, text);
  }

  rec['moved'] = moved;
  rec['created'] = created;
  rec['helixsr'] = coreVersion;
  rec['route'] = 'optiscaler';
  _writeMarker(markerPath, rec);
}

String _libraryPath(String text, String key, String helixCopy, String? found) {
  if (fileExists(helixCopy))
    return setIniValue(text, key, helixCopy, 'Libraries');
  if (found != null && fileExists(found))
    return setIniValue(text, key, found, 'Libraries');
  return text;
}

String _frameGen(String text, String enabled, String input, String output) {
  text = setIniValue(text, 'Enabled', enabled, 'FrameGen');
  text = setIniValue(text, 'FGInput', input, 'FrameGen');
  return setIniValue(text, 'FGOutput', output, 'FrameGen');
}

void _installDirect(GameInfo game, Core core, void Function(String) say) {
  final t = game.target;
  final srcFfx = core.fsrDll;

  if (game.fsrTargets.isNotEmpty) {
    for (final target in game.fsrTargets) {
      say('replacing ${p.basename(target)}');
      final orig = originalName(target);
      if (fileExists(target) && !fileExists(orig))
        File(target).renameSync(orig);
      File(srcFfx).copySync(target);
      core.syncNetworkFiles(p.dirname(target));
      _writeMarker(p.join(p.dirname(target), markerFile), {
        'helixsr': coreVersion,
        'files': [p.basename(target)],
        'route': 'direct',
      });
    }
  } else if (t.isNotEmpty && dirExists(t)) {
    // Standalone direct DLL drop into the executable directory.
    final createdDlls = <String>[];
    for (final name in dllFiles) {
      final dst = p.join(t, name);
      final orig = originalName(dst);
      if (fileExists(dst) && !fileExists(orig)) {
        File(dst).renameSync(orig);
      } else if (!fileExists(dst)) {
        createdDlls.add(name);
      }
      File(srcFfx).copySync(dst);
    }
    core.syncNetworkFiles(t);
    _writeMarker(p.join(t, markerFile), {
      'helixsr': coreVersion,
      'route': 'direct',
      'created_dlls': createdDlls,
    });
  }

  clearShaderCache(game);
  sanitizeGameConfig(game);
}

void _installDlssLoader(GameInfo game, Core core, void Function(String) say) {
  // EXPERIMENTAL (HelixSR 1.8.1): the DLSS loader as dxgi.dll plus HelixSR as
  // nvngx.dll next to the game's .exe, without OptiScaler.
  final t = game.target;
  if (!dirExists(t))
    throw EngineException('Game executable directory not found.');
  final srcLoader = core.path(loaderFolder, loaderDll);
  if (!fileExists(srcLoader)) {
    throw EngineException('HelixSR DLSS loader missing at: $srcLoader');
  }

  final helixDir = p.join(t, helixSrFolder);
  final backupDir = p.join(helixDir, backupFolder);
  Directory(backupDir).createSync(recursive: true);

  final moved = <String>[];
  for (final name in [loaderDll, nvngxCoreDll]) {
    final cur = p.join(t, name);
    final ours = name == loaderDll
        ? isDlssLoaderBinary(cur)
        : isHelixSrBinary(cur);
    if (fileExists(cur) && !ours) {
      final bak = p.join(backupDir, name);
      tryDelete(bak);
      File(cur).renameSync(bak);
      moved.add(name);
    }
  }

  say('copying loader');
  File(srcLoader).copySync(p.join(t, loaderDll));
  File(core.fsrDll).copySync(p.join(t, nvngxCoreDll));
  core.syncNetworkFiles(t);

  _writeMarker(p.join(helixDir, markerFile), {
    'helixsr': coreVersion,
    'route': 'dlss',
    'files': [loaderDll, nvngxCoreDll],
    'moved': moved,
    'created': <String>[],
  });
  clearShaderCache(game);
}

/// Removes every artifact of the OptiScaler, DLSS loader and direct routes.
void cleanupHelixSrFiles(GameInfo game) {
  if (game.isInZoi) restoreInZoiUserSettings();

  // 1. OptiScaler / DLSS loader route.
  final exe = game.exeFolder;
  if (exe != null && dirExists(exe)) {
    final t = exe;
    final helixDir = p.join(t, helixSrFolder);
    final markerPath = p.join(helixDir, markerFile);
    final backupDir = p.join(helixDir, backupFolder);

    if (fileExists(markerPath) || dirExists(helixDir)) {
      var opti = 'dxgi.dll';
      var route = '';
      var moved = <String>[];
      var created = <String>[];
      var iniMode = '';

      final data = fileExists(markerPath) ? _readMarker(markerPath) : null;
      if (data != null) {
        if (data['optiscaler'] != null) opti = '${data['optiscaler']}';
        if (data['route'] != null) route = '${data['route']}';
        if (data['ini'] != null) iniMode = '${data['ini']}';
        moved = _strings(data['moved']);
        created = _strings(data['created']);
      }

      if (route == 'dlss') {
        opti = loaderDll;
        final coreCopy = p.join(t, nvngxCoreDll);
        if (fileExists(coreCopy) && isHelixSrBinary(coreCopy))
          tryDelete(coreCopy);
        for (final extra in ['helixsr.log', 'helixsr_loader.log']) {
          tryDelete(p.join(t, extra));
        }
        for (final net in networkFiles) {
          tryDelete(p.join(t, net));
        }
      }

      final optiFile = p.join(t, opti);
      if (fileExists(optiFile) &&
          (route != 'dlss' || isDlssLoaderBinary(optiFile))) {
        tryDelete(optiFile);
      }

      final gameIni = p.join(t, 'OptiScaler.ini');
      final bIni = p.join(backupDir, 'OptiScaler.ini');
      if (iniMode == 'created') {
        tryDelete(gameIni);
        tryDelete(p.join(t, 'OptiScaler.log'));
      } else if (fileExists(bIni)) {
        tryCopy(bIni, gameIni);
      }

      for (final c in created) {
        tryDelete(p.join(t, c));
      }
      for (final m in moved) {
        final bp = p.join(backupDir, m);
        if (fileExists(bp)) tryCopy(bp, p.join(t, m));
      }

      tryDeleteDir(helixDir);
      tryDeleteDir(p.join(t, '_storage_', helixSrFolder));
      tryDelete(p.join(t, 'nvapi64.dll'));
    }
  }

  // 2. Direct FSR 3.1 replacement.
  for (final target in game.fsrTargets) {
    final orig = originalName(target);
    if (fileExists(orig)) {
      tryDelete(target);
      File(orig).renameSync(target);
    }
    final dir = p.dirname(target);
    for (final net in networkFiles) {
      tryDelete(p.join(dir, net));
    }
    tryDelete(p.join(dir, markerFile));
    tryDelete(p.join(dir, 'helixsr.log'));
  }

  // Standalone direct install next to the executable.
  final exeDir = game.target;
  if (exeDir.isNotEmpty && dirExists(exeDir)) {
    final exeMarker = p.join(exeDir, markerFile);
    if (fileExists(exeMarker)) {
      final data = _readMarker(exeMarker);
      for (final item in _strings(data?['created_dlls'])) {
        tryDelete(p.join(exeDir, item));
      }
      for (final name in dllFiles) {
        final dst = p.join(exeDir, name);
        final orig = originalName(dst);
        if (fileExists(orig)) {
          tryDelete(dst);
          try {
            File(orig).renameSync(dst);
          } catch (_) {}
        }
      }
      for (final net in networkFiles) {
        tryDelete(p.join(exeDir, net));
      }
      tryDelete(exeMarker);
      tryDelete(p.join(exeDir, 'helixsr.log'));
    }
  }
}

void uninstallHelixSr(GameInfo game) {
  cleanupHelixSrFiles(game);
  if (game.isReEngine ||
      game.installReFramework ||
      fileExists(p.join(game.target, 'reframework_revision.txt'))) {
    uninstallReFramework(game);
  }
}

void _updateMarkerVersion(String markerPath) {
  if (!fileExists(markerPath)) return;
  final data = _readMarker(markerPath);
  if (data == null) return;
  data['helixsr'] = coreVersion;
  _writeMarker(markerPath, data);
}

/// Refreshes HelixSR in every installed game after the network was rebuilt.
/// Returns the number of games updated.
int syncHelixSrToInstalledGames(List<GameInfo> games) {
  final core = Core.instance;
  if (!core.status().weightsBuilt) return 0;
  final src = core.fsrDll;
  if (!fileExists(src)) return 0;

  var count = 0;
  for (final g in games) {
    if (!g.installed) continue;
    try {
      var updated = false;
      final t = g.target;
      if (g.route == 'optiscaler' && t.isNotEmpty) {
        for (final dir in [
          p.join(t, helixSrFolder),
          p.join(t, '_storage_', helixSrFolder),
        ]) {
          if (!dirExists(dir)) continue;
          File(src).copySync(p.join(dir, ownDll));
          File(src).copySync(p.join(dir, ownSrDll));
          core.syncNetworkFiles(dir);
          updated = true;
        }
        _updateMarkerVersion(p.join(t, helixSrFolder, markerFile));
      } else if (g.route == 'dlss' && t.isNotEmpty) {
        final c = p.join(t, nvngxCoreDll);
        if (fileExists(c) && isHelixSrBinary(c)) {
          File(src).copySync(c);
          core.syncNetworkFiles(t);
          _updateMarkerVersion(p.join(t, helixSrFolder, markerFile));
          updated = true;
        }
      } else if (g.route == 'direct') {
        var anyTarget = false;
        for (final target in g.fsrTargets) {
          final dir = p.dirname(target);
          final marker = p.join(dir, markerFile);
          // Only targets HelixSR owns.
          if (!fileExists(originalName(target)) && !fileExists(marker))
            continue;
          anyTarget = true;
          File(src).copySync(target);
          core.syncNetworkFiles(dir);
          _updateMarkerVersion(marker);
          updated = true;
        }
        final exeMarker = t.isEmpty ? null : p.join(t, markerFile);
        if (!anyTarget && exeMarker != null && fileExists(exeMarker)) {
          for (final name in dllFiles) {
            final dst = p.join(t, name);
            if (fileExists(dst) && isHelixSrBinary(dst))
              File(src).copySync(dst);
          }
          core.syncNetworkFiles(t);
          _updateMarkerVersion(exeMarker);
          updated = true;
        }
      }
      if (updated) count++;
    } catch (_) {
      // Game running or file locked: leave it, the user can reinstall.
    }
  }
  return count;
}

// ---- logs and OptiScaler.ini -----------------------------------------------

String readGameLog(String gameFolder, String logName) {
  for (final path in [
    p.join(gameFolder, helixSrFolder, logName),
    p.join(gameFolder, logName),
  ]) {
    if (fileExists(path)) return readText(path);
  }
  return 'No log content found.';
}

String readOptiScalerIni(String gameFolder) {
  final path = p.join(gameFolder, 'OptiScaler.ini');
  return fileExists(path) ? readText(path) : '';
}

void saveOptiScalerIni(String gameFolder, String content) =>
    writeText(p.join(gameFolder, 'OptiScaler.ini'), content);
