/// Steam discovery: install roots, library folders, app manifests, artwork.
library;

import 'dart:io';

import 'package:path/path.dart' as p;

import 'models.dart';
import 'paths.dart';

void _addUnique(List<String> list, Set<String> seen, String? candidate) {
  if (candidate == null || candidate.isEmpty) return;
  final norm = normalizePath(candidate);
  if (norm.isNotEmpty && dirExists(norm) && seen.add(canonicalKey(norm))) {
    list.add(norm);
  }
}

List<String> _subdirs(String dir) {
  try {
    return Directory(dir)
        .listSync(followLinks: false)
        .whereType<Directory>()
        .map((d) => d.path)
        .toList();
  } catch (_) {
    return [];
  }
}

String? _windowsSteamPath() {
  try {
    final r = Process.runSync('reg', [
      'query',
      r'HKCU\Software\Valve\Steam',
      '/v',
      'SteamPath',
    ]);
    final m = RegExp(r'SteamPath\s+REG_SZ\s+(.+)').firstMatch('${r.stdout}');
    return m?.group(1)?.trim();
  } catch (_) {
    return null;
  }
}

/// Test hook: when set, replaces the machine-wide Steam root search.
List<String>? steamRootsOverride;

List<String> getSteamRoots() {
  if (steamRootsOverride != null) return steamRootsOverride!;
  final roots = <String>[];
  final seen = <String>{};
  if (isWindows) {
    _addUnique(roots, seen, _windowsSteamPath());
    _addUnique(roots, seen, r'C:\Program Files (x86)\Steam');
    _addUnique(roots, seen, r'C:\Program Files\Steam');
  }
  final home = homeDir();
  if (home.isNotEmpty) {
    for (final rel in [
      '.local/share/Steam',
      '.steam/steam',
      '.steam/root',
      '.var/app/com.valvesoftware.Steam/.local/share/Steam',
    ]) {
      _addUnique(roots, seen, p.join(home, rel));
    }
  }
  // SteamOS SD card and external drives: /run/media/<mount> and
  // /run/media/<user>/<mount>.
  if (!isWindows) {
    for (final d1 in _subdirs('/run/media')) {
      if (dirExists(p.join(d1, 'steamapps'))) _addUnique(roots, seen, d1);
      for (final d2 in _subdirs(d1)) {
        if (dirExists(p.join(d2, 'steamapps'))) _addUnique(roots, seen, d2);
      }
    }
  }
  return roots;
}

final RegExp _vdfPath = RegExp(r'"path"\s+"([^"]+)"');

List<String> getSteamLibraries() {
  final libs = <String>[];
  final seen = <String>{};
  for (final root in getSteamRoots()) {
    _addUnique(libs, seen, p.join(root, 'steamapps', 'common'));
    final vdf = p.join(root, 'steamapps', 'libraryfolders.vdf');
    if (!fileExists(vdf)) continue;
    try {
      for (final m in _vdfPath.allMatches(readText(vdf))) {
        final path = m.group(1)!.replaceAll(r'\\', r'\');
        _addUnique(libs, seen, p.join(path, 'steamapps', 'common'));
      }
    } catch (_) {}
  }
  return libs;
}

/// installdir (lower case) -> manifest.
Map<String, ManifestInfo> getSteamManifests() {
  final map = <String, ManifestInfo>{};
  for (final common in getSteamLibraries()) {
    final steamapps = p.dirname(common);
    if (!dirExists(steamapps)) continue;
    try {
      for (final f in Directory(steamapps).listSync().whereType<File>()) {
        final name = p.basename(f.path);
        if (!name.startsWith('appmanifest_') || !name.endsWith('.acf'))
          continue;
        try {
          final c = readText(f.path);
          final id = RegExp(r'"appid"\s+"(\d+)"').firstMatch(c);
          final nm = RegExp(r'"name"\s+"([^"]+)"').firstMatch(c);
          final dir = RegExp(r'"installdir"\s+"([^"]+)"').firstMatch(c);
          final flags = RegExp(r'"StateFlags"\s+"(\d+)"').firstMatch(c);
          if (id != null && nm != null && dir != null) {
            map[dir.group(1)!.toLowerCase()] = ManifestInfo(
              id.group(1)!,
              nm.group(1)!,
              dir.group(1)!,
              p.dirname(steamapps),
              stateFlags: int.tryParse(flags?.group(1) ?? '') ?? 4,
            );
          }
        } catch (_) {}
      }
    } catch (_) {}
  }
  return map;
}

/// First file called [name] in [dir] or its sub-folders (Steam keeps newer
/// art under `librarycache/<appid>/<hash>/`), two levels deep.
String? _findCached(String dir, String name, [int depth = 0]) {
  final direct = p.join(dir, name);
  if (fileExists(direct)) return direct;
  if (depth >= 2) return null;
  for (final d in _subdirs(dir)) {
    final hit = _findCached(d, name, depth + 1);
    if (hit != null) return hit;
  }
  return null;
}

/// Local library-cache art for [appId], or null. Remote URLs come from
/// artwork.dart. Covers: Steam's 2x portrait or HelixSR's own download first;
/// the plain library_600x900.jpg is only 300x450 in Steam's cache, so it is
/// returned only with [lowRes], as a last resort. The landscape header is
/// [findSteamHeader].
String? findSteamArtwork(
  String? appId, {
  bool hero = false,
  bool lowRes = false,
}) {
  if (appId == null || appId.isEmpty) return null;
  final files = hero
      ? ['library_hero.jpg']
      : ['library_600x900_2x.jpg', if (lowRes) 'library_600x900.jpg'];
  final downloaded = p.join(
    dataDir(),
    'cache',
    'covers',
    hero ? '${appId}_hero_v2.jpg' : '${appId}_cover_v2.jpg',
  );
  String? lookup(String file) {
    for (final root in getSteamRoots()) {
      final cache = p.join(root, 'appcache', 'librarycache');
      final flat = p.join(cache, '${appId}_$file');
      final hit =
          _findCached(p.join(cache, appId), file) ??
          (fileExists(flat) ? flat : null);
      if (hit != null) return hit;
    }
    return null;
  }

  final hi = lookup(files.first);
  if (hi != null) return hi;
  if (fileExists(downloaded)) return downloaded;
  return files.length > 1 ? lookup(files[1]) : null;
}

/// Landscape header from Steam's local cache, a last resort for a cover.
String? findSteamHeader(String appId) {
  for (final root in getSteamRoots()) {
    final cache = p.join(root, 'appcache', 'librarycache');
    for (final n in ['library_header.jpg', 'header.jpg']) {
      final hit = _findCached(p.join(cache, appId), n);
      if (hit != null) return hit;
    }
    final flat = p.join(cache, '${appId}_header.jpg');
    if (fileExists(flat)) return flat;
  }
  return null;
}

String steamArtUrl(String appId, {bool hero = false}) =>
    'https://shared.fastly.steamstatic.com/store_item_assets/steam/apps/$appId/${hero ? 'library_hero.jpg' : 'library_600x900.jpg'}';
