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
          if (id != null && nm != null && dir != null) {
            map[dir.group(1)!.toLowerCase()] = ManifestInfo(
              id.group(1)!,
              nm.group(1)!,
              dir.group(1)!,
              p.dirname(steamapps),
            );
          }
        } catch (_) {}
      }
    } catch (_) {}
  }
  return map;
}

/// Local library-cache art for [appId], or null. Remote URLs are built by
/// [steamArtUrl].
String? findSteamArtwork(String? appId, {bool hero = false}) {
  if (appId == null || appId.isEmpty) return null;
  final file = hero ? 'library_hero.jpg' : 'library_600x900.jpg';
  for (final root in getSteamRoots()) {
    final cache = p.join(root, 'appcache', 'librarycache');
    final cands = [
      p.join(cache, appId, file),
      p.join(cache, '${appId}_$file'),
      if (!hero) p.join(cache, appId, 'library_header.jpg'),
    ];
    for (final c in cands) {
      if (fileExists(c)) return c;
    }
  }
  final cached = p.join(
    dataDir(),
    'cache',
    'covers',
    hero ? '${appId}_hero.jpg' : '${appId}_600x900.jpg',
  );
  return fileExists(cached) ? cached : null;
}

String steamArtUrl(String appId, {bool hero = false}) =>
    'https://shared.fastly.steamstatic.com/store_item_assets/steam/apps/$appId/${hero ? 'library_hero.jpg' : 'library_600x900.jpg'}';
