/// HelixSR 3 support in the Dart engine, against a fake release. The fake
/// release has its own stand-in for upstream's setup/helixsr_bridge.py that
/// records its arguments, so upstream's code never runs here.
library;

import 'dart:convert';
import 'dart:io';

import 'package:archive/archive.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:helixsr_manager/engine/engine.dart';
import 'package:helixsr_manager/engine/steam.dart' as steam;
import 'package:helixsr_manager/ui/common/labels.dart';
import 'package:path/path.dart' as p;

const _fakeBridge = r'''
import json, os, sys
release, cmd, rest = sys.argv[1], sys.argv[2], sys.argv[3:]
with open(os.path.join(release, "calls.jsonl"), "a") as f:
    f.write(json.dumps([cmd] + rest) + "\n")
if os.environ.get("FAKE_BRIDGE_FAIL"):
    print(json.dumps({"ok": False, "error": "no game found", "messages": []}))
    sys.exit(1)
opts = dict(zip(rest[0::2], rest[1::2]))
ini = os.path.join(release, "fake-scaler.ini")
if cmd == "install" and opts.get("--way") == "scaler" and os.path.isfile(ini):
    # what upstream's installer leaves in the game: its record and HelixSR
    # Scaler's OptiScaler.ini
    game = opts["--game"]
    with open(os.path.join(game, "HelixSR-Scaler.files"), "w") as f:
        f.write("# HelixSR Scaler, installed by HelixSR Desktop\nname=dxgi.dll\ndxgi.dll\n")
    with open(ini, "rb") as src, open(os.path.join(game, "OptiScaler.ini"), "wb") as dst:
        dst.write(src.read())
print("noise")
print(json.dumps({"protocol": 1, "ok": True, "messages": ["installed"]}))
''';

void main() {
  late Directory tmp;
  late String release;

  void write(String path, List<int> data) {
    File(path)
      ..createSync(recursive: true)
      ..writeAsBytesSync(data);
  }

  String makeRelease({bool network = true, bool hlx = true}) {
    write(
      p.join(release, 'setup', 'helixsr_bridge.py'),
      utf8.encode(_fakeBridge),
    );
    write(p.join(release, 'HelixSR', 'helixsr.dll'), [
      ...utf8.encode('MZ\x00HelixSR 3.2.0\x00'),
      ...List.filled(64, 0),
      if (network) ...[...ascii.encode('HXSRNET1'), ...List.filled(24, 0)],
    ]);
    write(p.join(release, 'HLX-FSR4', dllSr), [
      ...utf8.encode('MZ HLX FSR 4 (4.1.2)'),
      ...List.filled(32, 0),
      if (hlx) ...[...ascii.encode('HLXFSR4D'), ...List.filled(16, 0)],
    ]);
    write(p.join(release, 'helixsr-scaler', 'OptiScaler.dll'), [0x4d, 0x5a]);
    return release;
  }

  List<List<String>> calls() {
    final f = File(p.join(release, 'calls.jsonl'));
    if (!f.existsSync()) return [];
    return [
      for (final l in f.readAsLinesSync())
        if (l.trim().isNotEmpty) (jsonDecode(l) as List).cast<String>(),
    ];
  }

  String makeGame(String name, {Map<String, List<int>> files = const {}}) {
    final dir = p.join(tmp.path, 'games', name);
    write(p.join(dir, 'game.exe'), List.filled(4096, 0));
    files.forEach((f, data) => write(p.join(dir, f), data));
    return dir;
  }

  setUp(() {
    tmp = Directory.systemTemp.createTempSync('hsr3_test');
    dataDirOverride = p.join(tmp.path, 'data');
    release = helixSr3DefaultDir();
    steam.steamRootsOverride = [];
    bridgePythonOverride = 'python3';
  });

  tearDown(() {
    dataDirOverride = null;
    bridgePythonOverride = null;
    tmp.deleteSync(recursive: true);
  });

  test('SHA-256 matches the standard test vectors', () {
    String hex(List<int> data, {int chunk = 0}) {
      final h = Sha256();
      if (chunk == 0) {
        h.add(data);
      } else {
        for (var i = 0; i < data.length; i += chunk) {
          h.add(
            data.sublist(i, i + chunk > data.length ? data.length : i + chunk),
          );
        }
      }
      return h.hexDigest();
    }

    expect(
      hex([]),
      'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855',
    );
    expect(
      hex(utf8.encode('abc')),
      'ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad',
    );
    final long = utf8.encode(
      'abcdbcdecdefdefgefghfghighijhijkijkljklmklmnlmnomnopnopq',
    );
    expect(
      hex(long, chunk: 7),
      '248d6a61d20638b8e5c026930c3e6039a33ce45964ff2167f6ecedd419db06c1',
    );
    expect(
      hex(List.filled(1000000, 0x61), chunk: 4096),
      'cdc76e5c9914fb9281a1c7e284d73e67f1809a48a497200e046d39ccc7112cd0',
    );
  });

  test('status reads the network and HLX FSR 4 trailers', () {
    expect(helixSr3Status().downloaded, isFalse);
    makeRelease(network: false);
    var st = helixSr3Status();
    expect(st.downloaded, isTrue);
    expect(st.scalerReady, isFalse);
    expect(st.dropinReady, isTrue);
    makeRelease(hlx: false);
    st = helixSr3Status();
    expect(st.scalerReady, isTrue);
    expect(st.dropinReady, isFalse);
    expect(st.version, '3.2.0');
  });

  test('scan recognises HelixSR Scaler and skips its own FSR DLLs', () {
    final dir = makeGame(
      'Scaled',
      files: {
        'nvngx_dlss.dll': [0],
        'OptiScaler.ini': utf8.encode('[HelixSR]\n'),
        'dxgi.dll': [0],
        'HelixSR/helixsr.dll': utf8.encode('MZ HelixSR 3.2.0 '),
        'OptiScaler/$dllSr': [0],
        'HelixSR-Scaler-backup/$dllSr': [0],
        'HelixSR-Scaler.files': utf8.encode(
          '# version=2.1.0\nname=winmm.dll\nwinmm.dll\n',
        ),
      },
    );
    final g = scanGame(dir, null, {});
    expect(g.route, 'scaler');
    expect(g.installedRoute, 'scaler');
    expect(g.installed, isTrue);
    expect(g.version, '3.2.0');
    expect(g.scalerVersion, '2.1.0');
    expect(g.optiDllName, 'winmm.dll');
    expect(g.fsrTargets, isEmpty);
    expect(g.protonLaunchOption, 'WINEDLLOVERRIDES="winmm=n,b" %command%');
    g.optiDllName = 'dxgi.dll';
    expect(g.protonLaunchOption, '');
  });

  test('scan recognises the HLX FSR 4 drop-in', () {
    final dir = makeGame(
      'Dropped',
      files: {
        dllSr: utf8.encode('MZ HLX FSR 4 (4.1.2)'),
        'amd_fidelityfx_upscaler_dx12.original.dll': [0],
        markerFile: utf8.encode(
          jsonEncode({'helixsr': '3.2.0', 'upscaler': 'HLX FSR 4'}),
        ),
      },
    );
    final g = scanGame(dir, null, {});
    expect(g.route, 'hlxfsr');
    expect(g.installed, isTrue);
    expect(routeChoices(null, g), contains('hlxfsr'));
  });

  test('routes and readiness', () {
    final g = scanGame(makeGame('Plain'), null, {});
    expect(routeChoices(null, g).first, 'scaler');
    expect(routeChoices(null, g), isNot(contains('hlxfsr')));
    makeRelease(hlx: false);
    final core = CoreStatus(
      version: coreVersion,
      coreDir: '',
      coreExists: true,
      networkEmbedded: false,
      networkSeparate: false,
      weightsSize: 0,
      kernelsSize: 0,
      dllSize: 0,
      hasPython: true,
      dlssLoaderAvailable: false,
      helixSr3: helixSr3Status(),
    );
    expect(core.routeReady('scaler'), isTrue);
    expect(core.routeReady('hlxfsr'), isFalse);
    expect(core.routeReady('optiscaler'), isFalse);
  });

  test('install and uninstall go through the bridge', () async {
    makeRelease();
    final dir = makeGame(
      'Bridge',
      files: {
        'nvngx_dlss.dll': [0],
      },
    );
    final g = scanGame(dir, null, {})
      ..route = 'scaler'
      ..optiDllName = 'version.dll';
    final lines = <String>[];
    await installHelixSr(g, log: lines.add);
    expect(lines, contains('installed'));
    final c = calls().last;
    expect(c.sublist(0, 5), [
      'install',
      '--game',
      normalizePath(dir),
      '--way',
      'scaler',
    ]);
    expect(c, containsAll(['--scaler', p.join(release, 'helixsr-scaler')]));
    expect(c, containsAll(['--scaler-name', 'version.dll']));

    g.installedRoute = 'scaler';
    g.installed = true;
    uninstallHelixSr(g);
    expect(calls().last, ['remove', '--game', normalizePath(dir)]);
  });

  group('HelixSR Scaler in Unity games', () {
    const scalerIni =
        '[Upscalers]\r\nDx11Upscaler=auto\r\n\r\n[Spoofing]\r\n'
        'StreamlineSpoofing=auto\r\nDxgi=auto\r\nDxgiFactoryWrapping=auto\r\n';

    String unityGame(String name, {bool dlss = true}) => makeGame(
      name,
      files: {
        'UnityPlayer.dll': [0x4d, 0x5a],
        'game_Data/globalgamemanagers': [0],
        if (dlss) 'game_Data/Plugins/x86_64/nvngx_dlss.dll': [0x4d, 0x5a],
        if (!dlss) 'amd_fidelityfx_dx12.dll': [0x4d, 0x5a],
      },
    );

    Future<(String, List<String>)> install(String dir, String ini) async {
      makeRelease();
      write(p.join(release, 'fake-scaler.ini'), utf8.encode(ini));
      final g = scanGame(dir, null, {})..route = 'scaler';
      final lines = <String>[];
      await installHelixSr(g, log: lines.add);
      return (File(p.join(dir, 'OptiScaler.ini')).readAsStringSync(), lines);
    }

    test('turns DXGI spoofing on when it is on auto', () async {
      final dir = unityGame('UnityScaler');
      expect(scanGame(dir, null, {}).unityHasDlss, isTrue);
      final (ini, lines) = await install(dir, scalerIni);
      expect(ini, contains('\r\nDxgi=true\r\n'));
      expect(ini, contains('DxgiFactoryWrapping=auto'));
      // HelixSR Scaler runs DX11 through HelixSR on auto (ffx_12).
      expect(ini, contains('Dx11Upscaler=auto'));
      expect(lines.join('\n'), contains('GPU spoofing'));
    });

    test("keeps the user's own choice", () async {
      final (ini, _) = await install(
        unityGame('UnityOff'),
        scalerIni.replaceFirst('Dxgi=auto', 'Dxgi=false'),
      );
      expect(ini, contains('Dxgi=false'));
      expect(ini, isNot(contains('Dxgi=true')));
    });

    test('leaves Unity games without DLSS alone', () async {
      final (ini, _) = await install(
        unityGame('UnityFsr', dlss: false),
        scalerIni,
      );
      expect(ini, contains('Dxgi=auto'));
    });
  });

  test('install refuses an unbuilt release', () async {
    makeRelease(network: false, hlx: false);
    final g = scanGame(makeGame('Unbuilt'), null, {})..route = 'scaler';
    await expectLater(installHelixSr(g), throwsA(isA<BridgeException>()));
    g.route = 'hlxfsr';
    await expectLater(installHelixSr(g), throwsA(isA<BridgeException>()));
    expect(calls(), isEmpty);
  });

  test('download verifies the checksum and extracts', () async {
    final arc = Archive()
      ..add(
        ArchiveFile.bytes(
          'HelixSR-$helixSr3Version/setup/helixsr_bridge.py',
          utf8.encode(_fakeBridge),
        ),
      )
      ..add(
        ArchiveFile.bytes(
          'HelixSR-$helixSr3Version/HelixSR/helixsr.dll',
          utf8.encode('MZ HelixSR 3.2.0'),
        ),
      )
      ..add(
        ArchiveFile.bytes(
          'HelixSR-$helixSr3Version/helixsr-setup.sh',
          utf8.encode('#!/bin/sh\n'),
        ),
      );
    final bytes = ZipEncoder().encode(arc);
    final zip = p.join(tmp.path, 'release.zip');
    File(zip).writeAsBytesSync(bytes);
    final sha = (Sha256()..add(bytes)).hexDigest();
    final url = Uri.file(zip).toString();
    await expectLater(
      helixSr3Download(log: (_) {}, url: url, sha256: '0' * 64),
      throwsA(isA<StateError>()),
    );
    expect(helixSr3Status().downloaded, isFalse);
    final dest = await helixSr3Download(log: (_) {}, url: url, sha256: sha);
    expect(dest, release);
    expect(helixSr3Status().downloaded, isTrue);
    if (!Platform.isWindows) {
      final mode = File(p.join(dest, 'helixsr-setup.sh')).statSync().mode;
      expect(mode & 0x40, isNonZero); // owner execute
    }
  });

  test('download refuses paths outside the release', () async {
    final arc = Archive()
      ..add(ArchiveFile.bytes('../evil.txt', utf8.encode('x')));
    final bytes = ZipEncoder().encode(arc);
    final zip = p.join(tmp.path, 'evil.zip');
    File(zip).writeAsBytesSync(bytes);
    await expectLater(
      helixSr3Download(
        log: (_) {},
        url: Uri.file(zip).toString(),
        sha256: (Sha256()..add(bytes)).hexDigest(),
      ),
      throwsA(isA<StateError>()),
    );
  });

  test("build stops before the setup's game list", () async {
    makeRelease();
    final touched = p.join(tmp.path, 'games-touched');
    write(
      p.join(release, 'helixsr-setup.sh'),
      utf8.encode(
        "#!/usr/bin/env bash\necho building\necho \"args: \$*\"\n"
        "echo '[helixsr-setup] looking for your games ...'\nsleep 20\ntouch $touched\n",
      ),
    );
    final lines = <String>[];
    final sw = Stopwatch()..start();
    final ok = await helixSr3Build(log: lines.add);
    expect(sw.elapsed.inSeconds, lessThan(10));
    expect(ok, isTrue);
    expect(lines, contains('args: --yes'));
    expect(lines.any((l) => l.contains('looking for your games')), isFalse);
    await Future<void>.delayed(const Duration(milliseconds: 300));
    expect(File(touched).existsSync(), isFalse);
  }, skip: Platform.isWindows ? 'the fake setup is a shell script' : false);
}
