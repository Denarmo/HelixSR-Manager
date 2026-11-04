/// Host integration: GPU list, handheld detection, launching games, opening
/// folders and running the HelixSR network build.
library;

import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:path/path.dart' as p;

import 'core.dart';
import 'helixsr3.dart';
import 'installer.dart';
import 'models.dart';
import 'paths.dart';

Future<List<GpuInfo>> getGpuInfo() async {
  final list = <GpuInfo>[];
  try {
    if (isWindows) {
      final r = await Process.run('powershell.exe', [
        '-NoProfile',
        '-Command',
        'Get-CimInstance Win32_VideoController | ForEach-Object { "\$(\$_.Name)|\$(\$_.AdapterRAM)|\$(\$_.DriverVersion)" }',
      ]);
      for (final line in LineSplitter.split('${r.stdout}')) {
        final parts = line.trim().split('|');
        if (parts.first.isEmpty) continue;
        final ram = parts.length > 1 ? int.tryParse(parts[1]) ?? 0 : 0;
        list.add(
          GpuInfo(
            parts.first,
            ramMb: ram ~/ (1024 * 1024),
            driver: parts.length > 2 ? parts[2] : 'N/A',
          ),
        );
      }
    } else {
      final r = await Process.run('sh', [
        '-c',
        'lspci 2>/dev/null | grep -Ei "vga|3d|display"',
      ]);
      for (final line in LineSplitter.split('${r.stdout}')) {
        final i = line.indexOf(': ');
        if (i > 0) list.add(GpuInfo(line.substring(i + 2).trim()));
      }
    }
  } catch (_) {}
  if (list.isEmpty) list.add(const GpuInfo('Direct3D 12 Compatible GPU'));
  return list;
}

/// Console mode is wanted when `--console`/`--handheld` is passed, when
/// HELIXSR_HANDHELD=1, on SteamOS/Bazzite game mode, or when a pad is present.
HandheldInfo detectHandheldEnvironment(List<String> args) {
  final env = Platform.environment;
  if (args.contains('--console') ||
      args.contains('--handheld') ||
      env['HELIXSR_HANDHELD'] == '1') {
    return const HandheldInfo(
      isHandheld: true,
      isControllerDetected: true,
      reason: 'Command-line flag or environment variable',
      device: 'Console mode',
    );
  }
  var steamOs = false;
  var bazzite = false;
  if (!isWindows) {
    try {
      final os = File('/etc/os-release').readAsStringSync().toLowerCase();
      steamOs = os.contains('steamos');
      bazzite = os.contains('bazzite');
    } catch (_) {}
    // Steam Gaming Mode runs the app inside gamescope.
    if (env['GAMESCOPE_WAYLAND_DISPLAY'] != null ||
        env['SteamGamepadUI'] == '1' ||
        env['SteamDeck'] == '1') {
      return HandheldInfo(
        isHandheld: true,
        isSteamOs: steamOs,
        isBazzite: bazzite,
        reason: 'Steam Gaming Mode',
        device: 'Steam Deck',
      );
    }
    try {
      final js = Directory('/dev/input')
          .listSync()
          .where((e) => p.basename(e.path).startsWith('js'))
          .toList();
      if (js.isNotEmpty) {
        return HandheldInfo(
          isHandheld: true,
          isControllerDetected: true,
          isSteamOs: steamOs,
          isBazzite: bazzite,
          reason: 'Gamepad detected (${p.basename(js.first.path)})',
          device: 'Controller',
        );
      }
    } catch (_) {}
  }
  return HandheldInfo(isSteamOs: steamOs, isBazzite: bazzite);
}

Future<bool> openFolder(String path) async {
  if (path.isEmpty || !FileSystemEntity.isDirectorySync(path)) return false;
  try {
    if (isWindows) {
      await Process.start('explorer.exe', [p.normalize(path)]);
    } else {
      await Process.start('xdg-open', [path], mode: ProcessStartMode.detached);
    }
    return true;
  } catch (_) {
    return false;
  }
}

/// Starts a Steam game through the steam:// URL handler.
Future<bool> launchGame(GameInfo game) async {
  if (game.appId == null) return false;
  final url = 'steam://run/${game.appId}';
  try {
    if (isWindows) {
      await Process.start('cmd', ['/c', 'start', '', url]);
    } else {
      await Process.start('xdg-open', [url], mode: ProcessStartMode.detached);
    }
    return true;
  } catch (_) {
    return false;
  }
}

/// Runs the HelixSR setup script that compiles the network into the core DLL
/// and streams its output. After a successful build, installed games are
/// refreshed. Completes with the number of updated games (or -1 on failure).
Future<int> buildNetwork({
  String dlssPath = '',
  required void Function(String line) log,
  required List<GameInfo> Function() installedGames,
  String core = 'legacy',
}) async {
  if (core == 'helixsr3') {
    return buildHelixSr3(
      dlssPath: dlssPath,
      log: log,
      installedGames: installedGames,
    );
  }
  return _buildLegacy(
    dlssPath: dlssPath,
    log: log,
    installedGames: installedGames,
  );
}

/// Downloads the official HelixSR 3 release if needed, runs its setup and
/// updates the games that have HelixSR 3. Games updated, or -1 on failure.
Future<int> buildHelixSr3({
  String dlssPath = '',
  required void Function(String line) log,
  required List<GameInfo> Function() installedGames,
}) async {
  try {
    log(
      "HelixSR $helixSr3Version: the setup downloads NVIDIA's DLSS 310.7.0 DLL from NVIDIA's GitHub "
      "(NVIDIA's license) and AMD's FSR 4 driver file (from an installed AMD driver, else AMD's driver "
      'package, about 420 MB) and builds HLX DLSS and HLX FSR 4 on this PC. This takes several minutes.',
    );
    await helixSr3Download(log: log);
    final ok = await helixSr3Build(
      log: log,
      rebuild: helixSr3Status().networkReady,
      dlssPath: dlssPath,
    );
    if (!ok) {
      log(
        "HelixSR $helixSr3Version's network was not built (see the lines above).",
      );
      return -1;
    }
    final st = helixSr3Status();
    log(
      'HelixSR $helixSr3Version is built'
      '${st.hlxReady ? '' : ' (HLX FSR 4 is not; run the build again to retry)'}',
    );
    var n = 0;
    for (final g in installedGames()) {
      final r = g.installedRoute;
      if (!g.installed || r == null || !helixSr3Routes.contains(r)) continue;
      try {
        g.route = r;
        helixSr3Install(g);
        n++;
      } catch (e) {
        log('${g.name}: $e');
      }
    }
    if (n > 0) log('Updated HelixSR $helixSr3Version in $n installed game(s).');
    return n;
  } catch (e) {
    log('Error during the HelixSR $helixSr3Version build: $e');
    return -1;
  }
}

Future<int> _buildLegacy({
  String dlssPath = '',
  required void Function(String line) log,
  required List<GameInfo> Function() installedGames,
}) async {
  final core = Core.instance;
  final List<String> cmd;
  if (isWindows) {
    cmd = [
      'powershell.exe',
      '-NoProfile',
      '-NonInteractive',
      '-ExecutionPolicy',
      'Bypass',
      '-File',
      p.join(core.dir, 'helixsr-setup.ps1'),
      '-Yes',
      '-Rebuild',
      if (dlssPath.isNotEmpty && fileExists(dlssPath)) ...['-Dlss', dlssPath],
    ];
  } else {
    final sh = p.join(core.dir, 'helixsr-setup.sh');
    final synth = p.join(core.dir, 'setup', 'lib', 'model', 'launch_synth');
    for (final f in [sh, synth]) {
      if (fileExists(f)) {
        try {
          Process.runSync('chmod', ['755', f]);
        } catch (_) {}
      }
    }
    cmd = [
      'bash',
      sh,
      '--yes',
      '--rebuild',
      if (dlssPath.isNotEmpty && fileExists(dlssPath)) ...['--dlss', dlssPath],
    ];
  }

  log('Starting HelixSR network compiler: ${cmd.join(' ')}');
  try {
    final proc = await Process.start(
      cmd.first,
      cmd.sublist(1),
      workingDirectory: core.dir,
      environment: {'PYTHONUNBUFFERED': '1'},
      mode: ProcessStartMode.normal,
    );
    var suppress = false;
    final done = Completer<void>();
    var open = 2;
    void closed() {
      if (--open == 0) done.complete();
    }

    void pump(Stream<List<int>> s) {
      s
          .transform(utf8.decoder)
          .transform(const LineSplitter())
          .listen(
            (line) {
              if (suppress) return;
              if (line.toLowerCase().contains('looking for games')) {
                suppress = true;
                log(
                  "(HelixSR Manager installs games itself - skipping the setup's game installer)",
                );
                return;
              }
              log(line);
            },
            onDone: closed,
            onError: (_) => closed(),
          );
    }

    pump(proc.stdout);
    pump(proc.stderr);
    final code = await proc.exitCode;
    await done.future;
    if (core.status().weightsBuilt) {
      log('Build finished successfully!');
      final n = syncHelixSrToInstalledGames(installedGames());
      if (n > 0) log('Updated HelixSR in $n installed game(s).');
      return n;
    }
    log('Build exited with code $code');
    return -1;
  } catch (e) {
    log('Error during build: $e');
    return -1;
  }
}

/// Reads the two logs and OptiScaler.ini of a game.
({String helixsr, String optiscaler, String ini}) readGameLogs(GameInfo g) {
  String safe(String Function() f) {
    try {
      return f();
    } catch (_) {
      return '';
    }
  }

  final noLog = 'No log content found.';
  final h = safe(() => readGameLog(g.target, 'helixsr.log'));
  final o = safe(() => readGameLog(g.target, 'OptiScaler.log'));
  return (
    helixsr: h == noLog ? '' : h,
    optiscaler: o == noLog ? '' : o,
    ini: safe(() => readOptiScalerIni(g.target)),
  );
}
