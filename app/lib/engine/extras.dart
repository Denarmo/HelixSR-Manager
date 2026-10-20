/// Per-game extras: inZOI settings, REFramework, shader caches and the
/// Capcom config sanitiser.
library;

import 'dart:convert';
import 'dart:io';

import 'package:archive/archive.dart';
import 'package:path/path.dart' as p;

import 'constants.dart';
import 'ini.dart';
import 'models.dart';
import 'paths.dart';

// ---- inZOI ----------------------------------------------------------------

const String _inZoiSection = '/Script/BlueClient.B1GameUserSettings';
const String _inZoiBackup = 'GameUserSettings.helixsr-backup.json';
const List<String> _inZoiKeys = ['DLSSValue', 'DLSSG', 'FSR3Value', 'FSR3FI'];

/// Test hook for the inZOI config folder.
String? inZoiConfigDirOverride;

/// inZOI keeps its graphics options in
/// %LOCALAPPDATA%\BlueClient\Saved\Config\Windows\GameUserSettings.ini.
/// Under Proton the same path sits in the game's compatdata prefix.
String inZoiUserSettingsPath() {
  if (inZoiConfigDirOverride != null) {
    return p.join(inZoiConfigDirOverride!, 'GameUserSettings.ini');
  }
  if (isWindows) {
    final local = Platform.environment['LOCALAPPDATA'] ?? '';
    return p.join(
      local,
      'BlueClient',
      'Saved',
      'Config',
      'Windows',
      'GameUserSettings.ini',
    );
  }
  final prefix = p.join(
    homeDir(),
    '.local',
    'share',
    'Steam',
    'steamapps',
    'compatdata',
    inZoiAppId,
    'pfx',
    'drive_c',
    'users',
    'steamuser',
    'AppData',
    'Local',
  );
  return p.join(
    prefix,
    'BlueClient',
    'Saved',
    'Config',
    'Windows',
    'GameUserSettings.ini',
  );
}

/// OptiScaler.ini values for inZOI (Unreal Engine on AMD fixes).
String applyInZoiOptiScalerIni(String text) {
  text = setIniValue(text, 'AutoExposure', 'true', 'InitFlags');
  text = setIniValue(text, 'ColorResourceBarrier', '4', 'Hotfix');
  text = setIniValue(text, 'MotionVectorResourceBarrier', '8', 'Hotfix');
  return text;
}

/// Selects the in-game upscaler that feeds HelixSR (DLSS for the OptiScaler
/// and loader routes, FSR 3 for direct). The game's own values are saved and
/// put back by [restoreInZoiUserSettings].
void applyInZoiUserSettings(GameInfo game) {
  final cfg = inZoiUserSettingsPath();
  if (!fileExists(cfg)) return; // written on first launch; install again then
  try {
    var text = readText(cfg);
    final backup = p.join(p.dirname(cfg), _inZoiBackup);
    if (!fileExists(backup)) {
      final original = {
        for (final k in _inZoiKeys) k: getUeIniValue(text, _inZoiSection, k),
      };
      writeText(backup, jsonEncode(original));
    }
    if (game.route == 'direct') {
      final fsr = int.tryParse(
        getUeIniValue(text, _inZoiSection, 'FSR3Value') ?? '',
      );
      if (fsr == null || fsr <= 0) {
        text = setUeIniValue(text, _inZoiSection, 'FSR3Value', '4');
      }
      text = setUeIniValue(text, _inZoiSection, 'DLSSValue', '0');
      text = setUeIniValue(text, _inZoiSection, 'DLSSG', 'False');
    } else {
      final dlss = int.tryParse(
        getUeIniValue(text, _inZoiSection, 'DLSSValue') ?? '',
      );
      if (dlss == null || dlss <= 0) {
        text = setUeIniValue(text, _inZoiSection, 'DLSSValue', '4');
      }
      text = setUeIniValue(text, _inZoiSection, 'FSR3Value', '0');
      text = setUeIniValue(text, _inZoiSection, 'FSR3FI', 'False');
      // DLSS-G only when OptiScaler translates it.
      final dlssg =
          game.route == 'optiscaler' && game.fgMode.startsWith('dlssg_');
      text = setUeIniValue(
        text,
        _inZoiSection,
        'DLSSG',
        dlssg ? 'True' : 'False',
      );
    }
    writeText(cfg, text);
  } catch (_) {}
}

void restoreInZoiUserSettings() {
  final cfg = inZoiUserSettingsPath();
  final backup = p.join(p.dirname(cfg), _inZoiBackup);
  if (!fileExists(backup)) return;
  try {
    if (fileExists(cfg)) {
      final original = jsonDecode(readText(backup)) as Map<String, dynamic>;
      var text = readText(cfg);
      for (final k in _inZoiKeys) {
        final v = original[k];
        text = v == null
            ? removeUeIniValue(text, _inZoiSection, k)
            : setUeIniValue(text, _inZoiSection, k, '$v');
      }
      writeText(cfg, text);
    }
    File(backup).deleteSync();
  } catch (_) {}
}

// ---- REFramework ----------------------------------------------------------

const List<String> _refFiles = [
  'dinput8.dll',
  'reframework_revision.txt',
  're2_framework_log.txt',
  're2_fw_config.txt',
  'reframework_crash.dmp',
  'reframework_accessed_files.txt',
  'reframework_faulty_files.txt',
  'reframework_loose_files.txt',
  'ref_ui.ini',
];

/// Test hook: bytes of a REFramework zip to use instead of downloading.
Future<List<int>?> Function()? reframeworkFetchOverride;

Future<List<int>?> _downloadReFramework() async {
  if (reframeworkFetchOverride != null) return reframeworkFetchOverride!();
  final client = HttpClient()..connectionTimeout = const Duration(seconds: 20);
  try {
    final req = await client.getUrl(
      Uri.parse(
        'https://github.com/praydog/REFramework-nightly/releases/latest/download/REFramework.zip',
      ),
    );
    req.headers.set('User-Agent', 'HelixSR-Manager/$appVersion');
    req.followRedirects = true;
    final resp = await req.close().timeout(const Duration(seconds: 60));
    if (resp.statusCode != 200) return null;
    final bytes = <int>[];
    await for (final c in resp) {
      bytes.addAll(c);
    }
    return bytes;
  } catch (_) {
    return null;
  } finally {
    client.close(force: true);
  }
}

/// Downloads the latest REFramework nightly (falls back to the cached copy
/// when offline) and drops dinput8.dll next to the game executable.
Future<void> installReFrameworkNightly(GameInfo game) async {
  final root = game.exeFolder ?? game.folder;
  if (root.isEmpty || !dirExists(root)) return;

  final cacheDir = p.join(dataDir(), 'cache', 'reframework');
  Directory(cacheDir).createSync(recursive: true);
  final cachedDll = p.join(cacheDir, 'dinput8.dll');
  final cachedRev = p.join(cacheDir, 'reframework_revision.txt');

  var downloaded = false;
  final zip = await _downloadReFramework();
  if (zip != null && zip.length > 100000) {
    try {
      final archive = ZipDecoder().decodeBytes(zip);
      for (final entry in archive.files) {
        if (!entry.isFile) continue;
        final name = p.basename(entry.name).toLowerCase();
        if (name == 'dinput8.dll') {
          File(cachedDll).writeAsBytesSync(entry.content as List<int>);
          downloaded = true;
        } else if (name == 'reframework_revision.txt') {
          File(cachedRev).writeAsBytesSync(entry.content as List<int>);
        }
      }
    } catch (_) {}
  }
  if (!downloaded && !fileExists(cachedDll)) return;

  final targets = [root];
  final sub = p.join(root, '_storage_');
  if (dirExists(sub)) targets.add(sub);
  for (final dir in targets) {
    File(cachedDll).copySync(p.join(dir, 'dinput8.dll'));
    if (fileExists(cachedRev)) {
      tryCopy(cachedRev, p.join(dir, 'reframework_revision.txt'));
    }
  }
}

void uninstallReFramework(GameInfo game) {
  final dirs = <String>{};
  if (dirExists(game.folder)) dirs.add(game.folder);
  if (game.exeFolder != null && dirExists(game.exeFolder!))
    dirs.add(game.exeFolder!);
  final sub = p.join(game.exeFolder ?? game.folder, '_storage_');
  if (dirExists(sub)) dirs.add(sub);
  for (final dir in dirs) {
    for (final f in _refFiles) {
      tryDelete(p.join(dir, f));
    }
    tryDeleteDir(p.join(dir, 'reframework'));
  }
}

// ---- shader caches and config ---------------------------------------------

/// Removes RE Engine and generic DX12 pipeline caches so the game compiles
/// fresh shaders. Returns whether anything was removed.
bool clearShaderCache(GameInfo game) {
  var cleared = false;
  final folders = <String>{};
  if (dirExists(game.folder)) folders.add(game.folder);
  if (game.exeFolder != null && dirExists(game.exeFolder!))
    folders.add(game.exeFolder!);

  void rm(String path) {
    if (fileExists(path)) {
      try {
        File(path).deleteSync();
        cleared = true;
      } catch (_) {}
    }
  }

  for (final dir in folders) {
    rm(p.join(dir, 'shader.cache2'));
    rm(p.join(dir, 'piplinelist.bin'));
    final sub = p.join(dir, '_storage_');
    if (dirExists(sub)) {
      rm(p.join(sub, 'shader.cache2'));
      rm(p.join(sub, 'piplinelist.bin'));
    }
    try {
      for (final f in Directory(dir).listSync().whereType<File>()) {
        final name = p.basename(f.path);
        final lower = name.toLowerCase();
        if (lower.endsWith('.bin') &&
            (lower.contains('shader') || lower.contains('pipeline'))) {
          rm(f.path);
        }
      }
    } catch (_) {}
  }
  return cleared;
}

/// Capcom RE Engine config.ini: drop stale GPU adapter locks, turn off
/// DLSS Reflex / Streamline FG and select FSR3.
void sanitizeGameConfig(GameInfo game) {
  final cfg = p.join(game.folder, 'config.ini');
  if (!fileExists(cfg)) return;
  try {
    var text = readText(cfg);
    text = text.replaceAll(
      RegExp(
        r'^\[Render/Adapter\][\r\n]+(?:[A-Za-z0-9_]+=[^\r\n]*[\r\n]+)*',
        multiLine: true,
      ),
      '',
    );
    text = text.replaceAll(
      RegExp(r'^DLSSReflexLowLatency=[^\r\n]*', multiLine: true),
      'DLSSReflexLowLatency=OFF',
    );
    text = text.replaceAll(
      RegExp(r'^FrameGeneration=[^\r\n]*', multiLine: true),
      'FrameGeneration=OFF',
    );
    if (RegExp(r'^UpscalingAlgorithm=', multiLine: true).hasMatch(text)) {
      text = text.replaceAll(
        RegExp(r'^UpscalingAlgorithm=[^\r\n]*', multiLine: true),
        'UpscalingAlgorithm=FSR3',
      );
    }
    writeText(cfg, text);
  } catch (_) {}
}
