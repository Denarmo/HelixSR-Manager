/// Cover art lookup. Every game gets art when any source has it:
///
///  1. Steam's local library cache and HelixSR's own download cache.
///  2. For Steam games: the Steam CDN, trying several image names and mirrors,
///     then the store's `appdetails` header image.
///  3. For every other game (Epic, GOG, custom folders): the Steam app id is
///     looked up by name through the Steam store search, remembered on disk,
///     and the art then comes from step 2.
///
/// Downloaded images are kept in `<dataDir>/cache/covers`, so each is fetched
/// once. Pure Dart (dart:io).
library;

import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:path/path.dart' as p;

import 'models.dart';
import 'paths.dart';
import 'steam.dart';

/// Test hook: replaces the HTTP GET used for all lookups. Returns the body
/// bytes, or null on any failure.
Future<List<int>?> Function(Uri url)? artworkFetchOverride;

/// Test hook: turns all network lookups off (UI tests).
bool artworkNetworkEnabled = true;

const _cdns = [
  'https://shared.fastly.steamstatic.com/store_item_assets/steam/apps',
  'https://cdn.cloudflare.steamstatic.com/steam/apps',
  'https://cdn.akamai.steamstatic.com/steam/apps',
  'https://steamcdn-a.akamaihd.net/steam/apps',
];

/// Image names to try, best first. The portrait capsule is the real cover;
/// the rest are landscape fallbacks that [BoxFit.cover] crops.
List<String> _names({required bool hero}) => hero
    ? const [
        'library_hero.jpg',
        'library_hero_blur.jpg',
        'page_bg_generated_v6b.jpg',
        'header.jpg',
      ]
    : const [
        'library_600x900.jpg',
        'library_600x900_2x.jpg',
        'portrait.png',
        'header.jpg',
        'capsule_616x353.jpg',
        'capsule_467x181.jpg',
        'capsule_231x87.jpg',
      ];

/// Candidate remote URLs for [appId], best first.
List<String> steamArtUrls(String appId, {bool hero = false}) => [
  for (final n in _names(hero: hero))
    for (final cdn in _cdns) '$cdn/$appId/$n',
];

Directory _coverDir() {
  final d = Directory(p.join(dataDir(), 'cache', 'covers'));
  try {
    d.createSync(recursive: true);
  } catch (_) {}
  return d;
}

bool _isImage(List<int> b) {
  if (b.length < 1024) return false;
  final jpg = b[0] == 0xFF && b[1] == 0xD8;
  final png = b[0] == 0x89 && b[1] == 0x50 && b[2] == 0x4E && b[3] == 0x47;
  final webp = b[0] == 0x52 && b[1] == 0x49 && b[2] == 0x46 && b[3] == 0x46;
  return jpg || png || webp;
}

Future<List<int>?> _get(Uri url) async {
  if (!artworkNetworkEnabled) return null;
  final o = artworkFetchOverride;
  if (o != null) return o(url);
  final client = HttpClient()
    ..connectionTimeout = const Duration(seconds: 8)
    ..userAgent = 'HelixSR-Manager';
  try {
    final req = await client.getUrl(url).timeout(const Duration(seconds: 8));
    final res = await req.close().timeout(const Duration(seconds: 10));
    if (res.statusCode != 200) {
      await res.drain<void>();
      return null;
    }
    final out = BytesBuilder(copy: false);
    await for (final chunk in res.timeout(const Duration(seconds: 20))) {
      out.add(chunk);
    }
    return out.takeBytes();
  } catch (_) {
    return null;
  } finally {
    client.close(force: true);
  }
}

// ---------------------------------------------------------------------------
// Name matching
// ---------------------------------------------------------------------------

final _edition = RegExp(
  r'\b(game of the year|goty|definitive|ultimate|complete|deluxe|digital|'
  r'standard|gold|premium|remastered|remaster|enhanced|director.?s cut|'
  r'anniversary|collection|edition|bundle|pc|x64|x86|win64|win32|shipping)\b',
);

/// Lower-case alphanumerics only, trademark signs and editions dropped.
String normalizeGameName(String name) {
  var s = name.toLowerCase().replaceAll(RegExp(r'[™®©]'), '');
  s = s.replaceAll(RegExp(r"['’]"), '');
  s = s.replaceAll(_edition, ' ');
  s = s.replaceAll(RegExp(r'[^a-z0-9]+'), ' ').trim();
  return s.replaceAll(RegExp(r'\s+'), ' ');
}

/// "SomeGame_v1.2" / "SomeGameFolder" -> "Some Game".
String prettifyFolderName(String name) {
  var s = name.replaceAll(RegExp(r'[_ ][vV]?\d+(\.\d+)+\b'), ' ');
  s = s.replaceAll(RegExp(r'[_\-.]+'), ' ');
  s = s.replaceAllMapped(
    RegExp(r'([a-z0-9])([A-Z])'),
    (m) => '${m[1]} ${m[2]}',
  );
  return s.replaceAll(RegExp(r'\s+'), ' ').trim();
}

/// Search terms for [game], most specific first.
List<String> nameQueries(GameInfo game) {
  final out = <String>[];
  void add(String s) {
    s = s.trim();
    if (s.length >= 2 && !out.contains(s)) out.add(s);
  }

  add(game.name);
  add(prettifyFolderName(game.name));
  add(prettifyFolderName(p.basename(game.folder)));
  add(normalizeGameName(game.name));
  // Drop a subtitle: "Game: The Remake" -> "Game".
  final cut = game.name.split(RegExp(r'\s[:\-–—]\s|:')).first;
  add(cut);
  return out;
}

int _score(String wanted, String candidate) {
  final a = normalizeGameName(wanted);
  final b = normalizeGameName(candidate);
  if (a.isEmpty || b.isEmpty) return 0;
  if (a == b) return 100;
  final ta = a.split(' ').toSet();
  final tb = b.split(' ').toSet();
  final common = ta.intersection(tb).length;
  final total = ta.union(tb).length;
  var s = (60 * common / total).round();
  if (b.startsWith(a) || a.startsWith(b)) s += 15;
  return s;
}

// ---------------------------------------------------------------------------
// App id lookup (non-Steam games, or Steam games without a manifest)
// ---------------------------------------------------------------------------

File _idCacheFile() => File(p.join(dataDir(), 'cache', 'appids.json'));

Map<String, dynamic>? _idCache;

Map<String, dynamic> _loadIds() {
  if (_idCache != null) return _idCache!;
  try {
    final v = jsonDecode(_idCacheFile().readAsStringSync());
    if (v is Map<String, dynamic>) return _idCache = v;
  } catch (_) {}
  return _idCache = <String, dynamic>{};
}

void _saveIds() {
  try {
    final f = _idCacheFile();
    f.parent.createSync(recursive: true);
    f.writeAsStringSync(jsonEncode(_idCache));
  } catch (_) {}
}

/// Forgets the in-memory lookup cache (tests).
void resetArtworkCaches() {
  _idCache = null;
  _inflight.clear();
}

/// The Steam app id that best matches [game], or null. Remembered on disk;
/// "no match" is remembered for a week so a missing game is not re-queried on
/// every start.
Future<String?> resolveAppId(GameInfo game) async {
  if (game.appId != null && game.appId!.isNotEmpty) return game.appId;
  final key = normalizeGameName(game.name);
  if (key.isEmpty) return null;
  final ids = _loadIds();
  final hit = ids[key];
  if (hit is Map) {
    final id = hit['id'];
    if (id is String && id.isNotEmpty) return id;
    final at = DateTime.tryParse('${hit['at']}');
    if (at != null && DateTime.now().difference(at).inDays < 7) return null;
  }
  String? best;
  var bestScore = 0;
  var reached = false;
  for (final q in nameQueries(game).take(4)) {
    final url = Uri.https('store.steampowered.com', '/api/storesearch/', {
      'term': q,
      'cc': 'us',
      'l': 'en',
    });
    final bytes = await _get(url);
    if (bytes == null) continue;
    reached = true;
    try {
      final j = jsonDecode(utf8.decode(bytes));
      for (final item in (j['items'] as List? ?? const [])) {
        if (item is! Map || item['type'] != 'app') continue;
        final s = _score(q, '${item['name']}');
        if (s > bestScore) {
          bestScore = s;
          best = '${item['id']}';
        }
      }
    } catch (_) {}
    if (bestScore >= 100) break;
  }
  // Below ~60 the match is a different game that happens to share a word.
  final accepted = bestScore >= 60 ? best : null;
  if (accepted != null) {
    ids[key] = {'id': accepted};
    _saveIds();
  } else if (reached) {
    ids[key] = {'at': DateTime.now().toIso8601String()};
    _saveIds();
  }
  return accepted;
}

// ---------------------------------------------------------------------------
// Art download
// ---------------------------------------------------------------------------

final _inflight = <String, Future<String?>>{};

/// A file path with art for [game], downloading it first if needed. Null when
/// no source has any. Concurrent calls for the same image share one lookup.
Future<String?> resolveArtwork(GameInfo game, {bool hero = false}) {
  final key = '${game.id}|$hero';
  return _inflight[key] ??= _resolve(game, hero).then((v) {
    if (v == null) _inflight.remove(key);
    return v;
  });
}

Future<String?> _resolve(GameInfo game, bool hero) async {
  final id = game.appId ?? await resolveAppId(game);
  if (id == null) return null;

  final local = findSteamArtwork(id, hero: hero);
  if (local != null) return local;

  final dir = _coverDir();
  final target = File(
    p.join(dir.path, hero ? '${id}_hero.jpg' : '${id}_600x900.jpg'),
  );
  for (final url in steamArtUrls(id, hero: hero)) {
    final bytes = await _get(Uri.parse(url));
    if (bytes != null && _isImage(bytes)) {
      try {
        target.writeAsBytesSync(bytes);
        return target.path;
      } catch (_) {
        return null;
      }
    }
  }

  // Last resort: the header image the store page itself points at.
  final details = await _get(
    Uri.https('store.steampowered.com', '/api/appdetails', {
      'appids': id,
      'filters': 'basic',
    }),
  );
  if (details != null) {
    try {
      final j = jsonDecode(utf8.decode(details));
      final header = j[id]?['data']?['header_image'];
      if (header is String) {
        final bytes = await _get(Uri.parse(header));
        if (bytes != null && _isImage(bytes)) {
          target.writeAsBytesSync(bytes);
          return target.path;
        }
      }
    } catch (_) {}
  }
  return null;
}
