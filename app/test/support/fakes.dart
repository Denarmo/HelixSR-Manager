import 'dart:io';

import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:helixsr_manager/app/engine_api.dart';
import 'package:helixsr_manager/engine/engine.dart';

/// Loads the bundled fonts so screenshots show the real typography.
Future<void> loadFonts() async {
  Future<void> load(String family, List<String> files) async {
    final loader = FontLoader(family);
    for (final f in files) {
      loader.addFont(
        Future.value(ByteData.sublistView(File(f).readAsBytesSync())),
      );
    }
    await loader.load();
  }

  await load('IBM Plex Mono', [
    'assets/fonts/ibm_plex_mono/IBMPlexMono-Medium.ttf',
    'assets/fonts/ibm_plex_mono/IBMPlexMono-SemiBold.ttf',
    'assets/fonts/ibm_plex_mono/IBMPlexMono-Bold.ttf',
  ]);
  await load('Archivo Black', [
    'assets/fonts/archivo_black/ArchivoBlack-Regular.ttf',
  ]);
}

GameInfo fakeGame(
  String name, {
  bool installed = false,
  String route = 'optiscaler',
  List<String> inputs = const ['DLSS'],
  bool re = false,
  String? appId,
  String fg = 'auto',
}) {
  final g =
      GameInfo(
          id: name.hashCode.toString(),
          name: name,
          folder: '/games/$name',
          appId: appId,
          launcher: appId == null ? 'Custom' : 'Steam',
        )
        ..exeFolder = '/games/$name/bin'
        ..exeName = '${name.replaceAll(' ', '')}.exe'
        ..inputs = List.of(inputs)
        ..installed = installed
        ..route = route
        ..fgMode = fg
        ..isReEngine = re
        ..installReFramework = re;
  return g;
}

List<GameInfo> fakeLibrary() => [
  fakeGame(
    'Cyberpunk 2077',
    installed: true,
    inputs: ['DLSS', 'DLSS-G', 'XeSS'],
    appId: '1091500',
    fg: 'dlssg_fsrfg',
  ),
  fakeGame(
    'Resident Evil 4',
    installed: true,
    inputs: ['DLSS'],
    re: true,
    appId: '2050650',
  ),
  fakeGame(
    'Monster Hunter Wilds',
    re: true,
    inputs: ['DLSS'],
    appId: '2246340',
  ),
  fakeGame('Alan Wake 2', inputs: ['DLSS', 'DLSS-G'], appId: '108710'),
  fakeGame(
    'inZOI',
    installed: true,
    route: 'dlss',
    inputs: ['DLSS'],
    appId: '2456740',
  )..isInZoi = true,
  fakeGame(
    'Hogwarts Legacy',
    inputs: ['DLSS', 'XeSS', 'FSR 2'],
    appId: '990080',
  ),
  fakeGame('Black Myth Wukong', inputs: ['DLSS'], appId: '2358720'),
  fakeGame(
    'Starfield',
    installed: true,
    route: 'direct',
    inputs: ['DLSS', 'FSR 2'],
    appId: '1716740',
  ),
  fakeGame('Dragons Dogma 2', re: true, inputs: ['DLSS'], appId: '2054970'),
];

class FakeEngine implements EngineApi {
  FakeEngine({List<GameInfo>? games, this.built = true})
    : library = games ?? fakeLibrary();
  final List<GameInfo> library;
  final bool built;
  final installs = <String>[];
  final uninstalls = <String>[];

  @override
  Future<List<GameInfo>> scan(List<String> customFolders) async => library;

  @override
  Future<(GameInfo, List<String>)> install(GameInfo game) async {
    installs.add(
      '${game.name}:${game.route}:${game.optiDllName}:${game.fgMode}',
    );
    game.installed = true;
    return (game, ['copying HelixSR']);
  }

  @override
  Future<GameInfo> uninstall(GameInfo game) async {
    uninstalls.add(game.name);
    game.installed = false;
    return game;
  }

  @override
  Future<CoreStatus> coreStatus() async => CoreStatus(
    version: coreVersion,
    coreDir: '/opt/helixsr_core/HelixSR-$coreVersion',
    coreExists: true,
    networkEmbedded: built,
    networkSeparate: false,
    weightsSize: built ? 41943040 : 0,
    kernelsSize: built ? 9437184 : 0,
    dllSize: 52428800,
    hasPython: true,
    dlssLoaderAvailable: true,
  );

  @override
  Future<List<GpuInfo>> gpus() async => const [
    GpuInfo('AMD Radeon RX 7800 XT', ramMb: 16384),
  ];

  @override
  Future<int> sync(List<GameInfo> games) async => games.length;

  @override
  Future<int> buildNetwork({
    required String dlssPath,
    required void Function(String) log,
    required List<GameInfo> Function() games,
  }) async {
    log('Starting HelixSR network compiler');
    log('extracting weights ... ok');
    log('Build finished successfully!');
    return 0;
  }
}
