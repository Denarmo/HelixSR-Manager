import 'dart:convert';
import 'dart:math';
import 'dart:io';
import 'dart:typed_data';

import 'package:flutter_test/flutter_test.dart';
import 'package:helixsr_manager/engine/engine.dart';
import 'package:helixsr_manager/engine/extras.dart' as extras;
import 'package:helixsr_manager/engine/steam.dart' as steam;
import 'package:archive/archive.dart';
import 'package:path/path.dart' as p;

/// Builds a fake core with an embedded network and a fake game.
final rnd = Random(1);

void main() {
  late Directory tmp;
  late String core;

  setUp(() {
    tmp = Directory.systemTemp.createTempSync('hsr_test');
    core = p.join(tmp.path, 'core', 'HelixSR-$coreVersion');
    for (final f in [
      'optiscaler/OptiScaler.dll',
      'optiscaler/OptiScaler.ini',
      'optiscaler/fakenvapi.dll',
      'optiscaler/fakenvapi.ini',
      'amd-fsr/$dllSr',
      'amd-fsr/$amdFgFile',
      'dlss-loader/dxgi.dll',
    ]) {
      File(p.join(core, f))
        ..createSync(recursive: true)
        ..writeAsStringSync(
          f.endsWith('dxgi.dll') ? 'HelixSR DLSS loader' : 'x $f',
        );
    }
    File(p.join(core, 'optiscaler/OptiScaler.ini'))
        .writeAsStringSync('[Menu]\r\nDisableSplash=false\r\n[Hotfix]\r\n');
    final dll = BytesBuilder()
      ..add(utf8.encode('HelixSR 1.8.1 dll body'))
      ..add(Uint8List(64));
    final tail = ByteData(32);
    for (var i = 0; i < 8; i++) {
      tail.setUint8(i, embedMagic.codeUnitAt(i));
    }
    tail.setInt64(8, 1000, Endian.little);
    tail.setInt64(16, 2000, Endian.little);
    dll.add(tail.buffer.asUint8List());
    File(p.join(core, dllFsr)).writeAsBytesSync(dll.toBytes());
    Core.use(core);
    steam.steamRootsOverride = [];
  });

  tearDown(() => tmp.deleteSync(recursive: true));

  GameInfo makeGame(String name, {List<String> files = const []}) {
    final dir = p.join(tmp.path, 'games', name);
    for (final f in ['game.exe', 'nvngx_dlss.dll', ...files]) {
      File(p.join(dir, f))
        ..createSync(recursive: true)
        ..writeAsStringSync('orig $f');
    }
    return scanGame(dir, name, null);
  }

  test('core status sees the embedded network', () {
    final s = Core.instance.status();
    expect(s.networkEmbedded, isTrue);
    expect(s.weightsSize, 1000);
    expect(s.kernelsSize, 2000);
  });

  test('scan detects DLSS input and exe folder', () {
    final g = makeGame('Alpha');
    expect(g.inputs, contains('DLSS'));
    expect(g.exeName, 'game.exe');
    expect(g.installed, isFalse);
    expect(g.route, 'optiscaler');
  });

  test('optiscaler install then uninstall restores the game', () async {
    final g = makeGame('Beta', files: ['dxgi.dll']);
    g.fgMode = 'dlssg_fsrfg';
    await installHelixSr(g);
    final t = g.target;
    expect(
      File(p.join(t, 'dxgi.dll')).readAsStringSync(),
      contains('OptiScaler.dll'),
    );
    expect(File(p.join(t, 'HelixSR', ownDll)).existsSync(), isTrue);
    final ini = File(p.join(t, 'OptiScaler.ini')).readAsStringSync();
    expect(ini, contains('FGOutput = fsrfg'));
    expect(ini, contains('DisableSplash = true'));

    final again = scanGame(g.folder, 'Beta', null);
    expect(again.installed, isTrue);
    expect(again.fgMode, 'dlssg_fsrfg');

    uninstallHelixSr(again);
    expect(File(p.join(t, 'dxgi.dll')).readAsStringSync(), 'orig dxgi.dll');
    expect(Directory(p.join(t, 'HelixSR')).existsSync(), isFalse);
    expect(File(p.join(t, 'OptiScaler.ini')).existsSync(), isFalse);
    expect(scanGame(g.folder, 'Beta', null).installed, isFalse);
  });

  test('direct route swaps the game FSR dll and restores it', () async {
    final g = makeGame('Gamma', files: [dllSr]);
    g.route = 'direct';
    await installHelixSr(g);
    final target = g.fsrTargets.single;
    expect(isHelixSrBinary(target), isTrue);
    expect(
      File(
        p.join(p.dirname(target), 'amd_fidelityfx_upscaler_dx12.original.dll'),
      ).existsSync(),
      isTrue,
    );
    final again = scanGame(g.folder, 'Gamma', null);
    expect(again.route, 'direct');
    expect(again.installed, isTrue);
    uninstallHelixSr(again);
    expect(File(target).readAsStringSync(), 'orig $dllSr');
  });

  test('dlss loader route backs up and restores dxgi.dll', () async {
    final g = makeGame('Delta', files: ['dxgi.dll']);
    g.route = 'dlss';
    await installHelixSr(g);
    expect(isDlssLoaderBinary(p.join(g.target, 'dxgi.dll')), isTrue);
    expect(isHelixSrBinary(p.join(g.target, 'nvngx.dll')), isTrue);
    final again = scanGame(g.folder, 'Delta', null);
    expect(again.route, 'dlss');
    uninstallHelixSr(again);
    expect(
      File(p.join(g.target, 'dxgi.dll')).readAsStringSync(),
      'orig dxgi.dll',
    );
    expect(File(p.join(g.target, 'nvngx.dll')).existsSync(), isFalse);
  });

  test('RE Engine game gets REFramework and mirrors into _storage_', () async {
    final g = makeGame('Resident Evil Test');
    Directory(p.join(g.folder, '_storage_')).createSync();
    final re = scanGame(g.folder, 'Resident Evil Test', null);
    expect(re.isReEngine, isTrue);
    final zip = _zipWith(
      'dinput8.dll',
      List.generate(200000, (_) => rnd.nextInt(256)),
    );
    extras.reframeworkFetchOverride = () async => zip;
    await installHelixSr(re);
    expect(File(p.join(re.target, 'dinput8.dll')).existsSync(), isTrue);
    expect(re.protonLaunchOption, contains('dinput8'));
    uninstallHelixSr(scanGame(g.folder, 'x', null));
    expect(File(p.join(re.target, 'dinput8.dll')).existsSync(), isFalse);
    extras.reframeworkFetchOverride = null;
  });

  test('inZOI settings are applied and restored', () async {
    final cfgDir = p.join(tmp.path, 'cfg');
    extras.inZoiConfigDirOverride = cfgDir;
    final cfg = File(p.join(cfgDir, 'GameUserSettings.ini'))
      ..createSync(recursive: true)
      ..writeAsStringSync(
        '[/Script/BlueClient.B1GameUserSettings]\r\nDLSSValue=0\r\nFSR3Value=2\r\n',
      );
    final g = makeGame('inZOI');
    expect(g.isInZoi, isTrue);
    await installHelixSr(g);
    var text = cfg.readAsStringSync();
    expect(text, contains('DLSSValue=4'));
    expect(text, contains('FSR3Value=0'));
    expect(
      File(p.join(g.target, 'OptiScaler.ini')).readAsStringSync(),
      contains('ColorResourceBarrier = 4'),
    );
    uninstallHelixSr(scanGame(g.folder, 'inZOI', null));
    text = cfg.readAsStringSync();
    expect(text, contains('DLSSValue=0'));
    expect(text, contains('FSR3Value=2'));
    extras.inZoiConfigDirOverride = null;
  });

  group('Unity detection', () {
    GameInfo unityGame(
      String name,
      String exe, {
      List<String> files = const [],
      Map<String, String> text = const {},
      Map<String, List<int>> bytes = const {},
    }) {
      final dir = p.join(tmp.path, 'games', name);
      for (final f in [exe, ...files]) {
        File(p.join(dir, f))
          ..createSync(recursive: true)
          ..writeAsStringSync('x $f');
      }
      text.forEach(
        (f, c) => File(p.join(dir, f))
          ..createSync(recursive: true)
          ..writeAsStringSync(c),
      );
      bytes.forEach(
        (f, c) => File(p.join(dir, f))
          ..createSync(recursive: true)
          ..writeAsBytesSync(c),
      );
      return scanGame(dir, name, null);
    }

    test('IL2CPP + URP on Unity 6', () {
      final g = unityGame(
        'Ddv',
        'Dreamlight.exe',
        files: ['UnityPlayer.dll', 'GameAssembly.dll'],
        text: {
          'Dreamlight_Data/ScriptingAssemblies.json': '{"names":["Assembly-CSharp.dll","Unity.RenderPipelines.Universal.Runtime.dll"]}',
        },
        bytes: {
          'Dreamlight_Data/globalgamemanagers': [
            ...List.filled(16, 0),
            ...'6000.0.23f1'.codeUnits,
            0,
          ],
        },
      );
      expect(g.isUnity, isTrue);
      expect(g.tags, contains('UNITY'));
      expect(g.unity!.version, '6000.0.23f1');
      expect(g.unity!.backend, 'IL2CPP');
      expect(g.unity!.pipeline, 'URP');
      expect(g.unity!.hasD3D12, isFalse);
      expect(g.unity!.summary, 'Unity 6 · IL2CPP · URP');
    });

    test('Mono + Built-in with D3D12 player and BepInEx', () {
      final g = unityGame(
        'Val',
        'valheim.exe',
        files: [
          'UnityPlayer.dll',
          'D3D12/D3D12Core.dll',
          'valheim_Data/Managed/Assembly-CSharp.dll',
          'valheim_Data/Managed/UnityEngine.dll',
          'BepInEx/core/BepInEx.dll',
        ],
        bytes: {
          'valheim_Data/data.unity3d': [
            ...'UnityFS'.codeUnits,
            0,
            ...'5.x.x'.codeUnits,
            0,
            ...'2022.3.17f1'.codeUnits,
            0,
          ],
        },
      );
      expect(g.unity!.version, '2022.3.17f1');
      expect(g.unity!.backend, 'Mono');
      expect(g.unity!.pipeline, 'Built-in');
      expect(g.unity!.hasD3D12, isTrue);
      expect(g.unity!.hasBepInEx, isTrue);
      expect(g.unity!.summary, 'Unity 2022.3 · Mono · Built-in · D3D12');
    });

    test('HDRP is told from the Managed folder without a version', () {
      final g = unityGame(
        'Hd',
        'Game.exe',
        files: [
          'UnityPlayer.dll',
          'Game_Data/globalgamemanagers',
          'Game_Data/Managed/Assembly-CSharp.dll',
          'Game_Data/Managed/Unity.RenderPipelines.HighDefinition.Runtime.dll',
        ],
      );
      expect(g.unity!.version, isNull);
      expect(g.unity!.pipeline, 'HDRP');
      expect(g.unity!.summary, 'Unity · Mono · HDRP');
    });

    test('a non-Unity game is not tagged', () {
      final g = makeGame('Plain');
      expect(g.isUnity, isFalse);
      expect(g.tags, isNot(contains('UNITY')));
    });

    test('formatUnityVersion', () {
      expect(formatUnityVersion('6000.0.23f1'), 'Unity 6');
      expect(formatUnityVersion('6000.1.2f1'), 'Unity 6.1');
      expect(formatUnityVersion('2022.3.10f1'), 'Unity 2022.3');
      expect(formatUnityVersion(null), 'Unity');
    });
  });

  test('install refuses when the network is not built', () async {
    File(p.join(core, dllFsr)).writeAsStringSync('HelixSR 1.8.1 bare');
    final g = makeGame('Eps');
    expect(() => installHelixSr(g), throwsA(isA<EngineException>()));
  });

  test('ini helpers', () {
    expect(setIniValue('[A]\r\nk = 1\r\n', 'k', '2', 'A'), contains('k = 2'));
    expect(setIniValue('', 'k', '2', 'S'), '\r\n[S]\r\nk = 2\r\n');
    const ue = '[S]\r\nA=1\r\n[T]\r\nB=2\r\n';
    expect(getUeIniValue(ue, 'S', 'A'), '1');
    expect(setUeIniValue(ue, 'S', 'C', '3'), contains('A=1\r\nC=3\r\n[T]'));
    expect(removeUeIniValue(ue, 'S', 'A'), '[S]\r\n[T]\r\nB=2\r\n');
    // the last section runs to the end of the file
    const last = '[S]\r\nA=1\r\n';
    expect(setUeIniValue(last, 'S', 'A', '9'), '[S]\r\nA=9\r\n');
    expect(setUeIniValue(last, 'S', 'B', '2'), '[S]\r\nA=1\r\nB=2\r\n');
  });
}

List<int> _zipWith(String name, List<int> content) {
  final a = Archive()..addFile(ArchiveFile(name, content.length, content));
  return ZipEncoder().encode(a);
}
