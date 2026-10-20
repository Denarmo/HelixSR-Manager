import 'dart:convert';
import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:helixsr_manager/engine/engine.dart';
import 'package:helixsr_manager/engine/steam.dart' show steamRootsOverride;

void main() {
  late Directory tmp;
  late List<Uri> calls;
  final jpg = <int>[0xFF, 0xD8, ...List.filled(2000, 7)];

  setUp(() {
    tmp = Directory.systemTemp.createTempSync('hsr_art');
    dataDirOverride = tmp.path;
    steamRootsOverride = [];
    artworkNetworkEnabled = true;
    resetArtworkCaches();
    calls = [];
  });
  tearDown(() {
    artworkFetchOverride = null;
    dataDirOverride = null;
    tmp.deleteSync(recursive: true);
  });

  GameInfo game(String name, {String? appId}) =>
      GameInfo(id: name, name: name, folder: '/g/$name', appId: appId);

  test('name normalisation drops editions and symbols', () {
    expect(normalizeGameName("Marvel's Spider-Man™ Remastered"),
        'marvels spider man');
    expect(prettifyFolderName('CyberPunk_2077_v1.2'), 'Cyber Punk 2077');
  });

  test('falls back through CDN names until one serves an image', () async {
    artworkFetchOverride = (u) async {
      calls.add(u);
      return u.path.endsWith('header.jpg') ? jpg : null;
    };
    final path = await resolveArtwork(game('A', appId: '10'));
    expect(path, isNotNull);
    expect(File(path!).existsSync(), isTrue);
    expect(calls.length, greaterThan(4));
  });

  test('non-Steam game is matched by name and remembered', () async {
    artworkFetchOverride = (u) async {
      calls.add(u);
      if (u.path.contains('storesearch')) {
        return utf8.encode(jsonEncode({
          'items': [
            {'type': 'app', 'id': 111, 'name': 'Hades II'},
            {'type': 'app', 'id': 222, 'name': 'Hades'},
          ],
        }));
      }
      return jpg;
    };
    final g = game('Hades');
    expect(await resolveAppId(g), '222');
    resetArtworkCaches();
    calls.clear();
    expect(await resolveAppId(g), '222'); // from disk, no network
    expect(calls, isEmpty);
    expect(await resolveArtwork(g), endsWith('222_600x900.jpg'));
  });

  test('unrelated search results are rejected', () async {
    artworkFetchOverride = (u) async => utf8.encode(jsonEncode({
          'items': [
            {'type': 'app', 'id': 9, 'name': 'Totally Different Thing'},
          ],
        }));
    expect(await resolveAppId(game('Obscure Indie Game')), isNull);
    expect(await resolveArtwork(game('Obscure Indie Game')), isNull);
  });

  test('short title leading a longer Steam title still matches', () async {
    artworkFetchOverride = (u) async => utf8.encode(jsonEncode({
          'items': [
            {'type': 'app', 'id': 5, 'name': 'HoloCure - Save the Fans!'},
            {'type': 'app', 'id': 6, 'name': 'Holo Something Else'},
            {'type': 'app', 'id': 7, 'name': 'In Konbini: One Store. Many Stories.'},
          ],
        }));
    expect(await resolveAppId(game('HoloCure')), '5');
    expect(await resolveAppId(game('inKonbini')), '7');
  });
}
