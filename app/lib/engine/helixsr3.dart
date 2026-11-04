/// HelixSR 3 (upstream lonewolf0622/HelixSR 3.x: HLX DLSS, HLX FSR 4,
/// HelixSR Scaler). Same behaviour as the HelixSR 3 block in
/// src/linux/helixsr_swapper_linux.py.
///
/// HelixSR 1.9 and later may only be redistributed unmodified and complete,
/// as an official release (HelixSR Freeware License, section 2), so it is not
/// bundled: the official release is downloaded from upstream's GitHub
/// (checked by SHA-256), upstream's own setup builds the network and HLX FSR
/// 4's shaders on this PC, and games are installed through upstream's app
/// bridge (setup/helixsr_bridge.py, the JSON interface HelixSR Desktop uses),
/// so the Manager, upstream's setup scripts and HelixSR Desktop can update or
/// remove each other's installs.
library;

import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'dart:typed_data';

import 'package:archive/archive.dart';
import 'package:path/path.dart' as p;

import 'constants.dart';
import 'ini.dart';
import 'models.dart';
import 'paths.dart';

const String helixSr3Version = '3.2.0';
const String helixSr3Url =
    'https://github.com/lonewolf0622/HelixSR/releases/download/v$helixSr3Version/HelixSR-$helixSr3Version.zip';
const String helixSr3Sha256 =
    'a4e83da8b4335a886197aef10e8f8a8947a2e32e5e1eebfdf060ff00724c17c7';
const int helixSr3Size = 217396302;

/// "scaler": HelixSR Scaler next to the game's .exe (HLX DLSS through the
/// game's DLSS / XeSS / FSR option, HLX FSR 4 in its menu). "hlxfsr": HLX FSR 4
/// in place of the game's FSR 3.1 DLL.
const List<String> helixSr3Routes = ['scaler', 'hlxfsr'];
const Map<String, String> _ways = {'scaler': 'scaler', 'hlxfsr': 'fsr'};

/// The file names HelixSR Scaler can take in a game (upstream SCALER_NAMES).
const List<String> scalerDllNames = [
  'dxgi.dll',
  'winmm.dll',
  'version.dll',
  'dbghelp.dll',
  'd3d12.dll',
  'wininet.dll',
  'winhttp.dll',
];
const String scalerRecord = 'HelixSR-Scaler.files';
const String scalerBackupDir = 'HelixSR-Scaler-backup';

/// Folders the game scan never walks into (HelixSR's own).
const Set<String> scanSkipDirs = {
  'helixsr',
  'helixsr-scaler-backup',
  'helixsr-fsrfg',
};

final String _dll = p.join('HelixSR', 'helixsr.dll');
final String _hlxDll = p.join('HLX-FSR4', dllSr);
final String _bridge = p.join('setup', 'helixsr_bridge.py');
const String _scalerDir = 'helixsr-scaler';
const String buildStopLine = 'looking for your games';

class HelixSr3Status {
  const HelixSr3Status({
    required this.version,
    required this.releaseDir,
    required this.downloaded,
    required this.networkReady,
    required this.hlxReady,
    required this.scalerPresent,
  });

  final String version;
  final String releaseDir;
  final bool downloaded;
  final bool networkReady;
  final bool hlxReady;
  final bool scalerPresent;

  bool get scalerReady => networkReady && scalerPresent;
  bool get dropinReady => hlxReady;

  /// Whether [route] (scaler / hlxfsr) can be installed now.
  bool ready(String route) => route == 'scaler' ? scalerReady : dropinReady;
}

String helixSr3DefaultDir() =>
    p.join(dataDir(), 'core', 'HelixSR-$helixSr3Version');

bool isHelixSr3Release(String dir) =>
    dir.isNotEmpty &&
    fileExists(p.join(dir, _bridge)) &&
    fileExists(p.join(dir, _dll));

/// $HELIXSR3_RELEASE (a release extracted for upstream's setup scripts), else
/// the Manager's download in the data folder (shared with the Linux edition
/// and the Decky plugin).
String helixSr3ReleaseDir() {
  final env = Platform.environment['HELIXSR3_RELEASE'];
  if (env != null && isHelixSr3Release(normalizePath(env))) {
    return normalizePath(env);
  }
  return helixSr3DefaultDir();
}

Uint8List _tail(String path, int offset, int length) {
  RandomAccessFile? f;
  try {
    f = File(path).openSync();
    final len = f.lengthSync();
    if (len < offset) return Uint8List(0);
    f.setPositionSync(len - offset);
    return f.readSync(length);
  } catch (_) {
    return Uint8List(0);
  } finally {
    f?.closeSync();
  }
}

bool _tailIs(String path, int offset, String magic) =>
    latin1.decode(_tail(path, offset, magic.length), allowInvalid: true) ==
    magic;

final RegExp _versionRe = RegExp(r'HelixSR (\d+\.\d+\.\d+)');

/// "HelixSR x.y.z" inside a HelixSR DLL (first 4 MB).
String? binaryVersion(String path) {
  RandomAccessFile? f;
  try {
    f = File(path).openSync();
    final n = f.lengthSync() < (4 << 20) ? f.lengthSync() : (4 << 20);
    return _versionRe.firstMatch(latin1.decode(f.readSync(n)))?.group(1);
  } catch (_) {
    return null;
  } finally {
    f?.closeSync();
  }
}

HelixSr3Status helixSr3Status() {
  final d = helixSr3ReleaseDir();
  final present = isHelixSr3Release(d);
  final dll = p.join(d, _dll);
  return HelixSr3Status(
    version: (present ? binaryVersion(dll) : null) ?? helixSr3Version,
    releaseDir: d,
    downloaded: present,
    networkReady: present && _tailIs(dll, 32, embedMagic),
    hlxReady: present && _tailIs(p.join(d, _hlxDll), 24, 'HLXFSR4D'),
    scalerPresent:
        present && fileExists(p.join(d, _scalerDir, 'OptiScaler.dll')),
  );
}

// ---- download ----------------------------------------------------------

/// Downloads and extracts the official HelixSR 3 release into the data
/// folder (once). [url] / [sha256] are test hooks.
Future<String> helixSr3Download({
  required void Function(String) log,
  String? url,
  String? sha256,
}) async {
  final dest = helixSr3DefaultDir();
  if (isHelixSr3Release(dest)) return dest;
  url ??= helixSr3Url;
  final want = (sha256 ?? helixSr3Sha256).toLowerCase();
  final base = p.dirname(dest);
  Directory(base).createSync(recursive: true);
  final zipPath = p.join(base, 'HelixSR-$helixSr3Version.zip.partial');
  log(
    'Downloading HelixSR $helixSr3Version from $url (${helixSr3Size >> 20} MB)',
  );
  final uri = Uri.parse(url);
  final hash = Sha256();
  final sink = File(zipPath).openWrite();
  try {
    if (uri.scheme == 'file') {
      await for (final chunk in File(uri.toFilePath()).openRead()) {
        hash.add(chunk);
        sink.add(chunk);
      }
    } else {
      final client = HttpClient()..userAgent = 'HelixSR-Manager/$appVersion';
      try {
        final res = await (await client.getUrl(uri)).close();
        if (res.statusCode != 200) {
          throw HttpException('HTTP ${res.statusCode}', uri: uri);
        }
        final total = res.contentLength;
        var done = 0;
        var next = 0;
        await for (final chunk in res) {
          hash.add(chunk);
          sink.add(chunk);
          done += chunk.length;
          if (total > 0 && done * 100 ~/ total >= next) {
            log('  ${done * 100 ~/ total}% (${done >> 20} MB)');
            next += 10;
          }
        }
      } finally {
        client.close();
      }
    }
  } finally {
    await sink.close();
  }
  final got = hash.hexDigest();
  if (got != want) {
    tryDelete(zipPath);
    throw StateError(
      'HelixSR-$helixSr3Version.zip: checksum mismatch (got $got)',
    );
  }
  log('Checksum OK, extracting');
  final tmp = p.join(base, '.HelixSR-$helixSr3Version.partial');
  tryDeleteDir(tmp);
  Directory(tmp).createSync(recursive: true);
  try {
    _extract(zipPath, tmp);
    final inner = p.join(tmp, 'HelixSR-$helixSr3Version');
    final src = dirExists(inner) ? inner : tmp;
    if (!isHelixSr3Release(src)) {
      throw StateError('the downloaded zip is not a HelixSR 3 release');
    }
    markExecutables(src);
    tryDeleteDir(dest);
    Directory(src).renameSync(dest);
  } finally {
    tryDeleteDir(tmp);
    tryDelete(zipPath);
  }
  log('HelixSR $helixSr3Version is in $dest');
  return dest;
}

void _extract(String zipPath, String dest) {
  final root = p.normalize(p.absolute(dest));
  final archive = ZipDecoder().decodeStream(InputFileStream(zipPath));
  try {
    for (final e in archive) {
      final target = p.normalize(p.join(root, e.name));
      if (target != root && !p.isWithin(root, target)) {
        throw StateError('unsafe path in the HelixSR zip: ${e.name}');
      }
    }
    for (final e in archive) {
      final target = p.normalize(p.join(root, e.name));
      if (e.isDirectory) {
        Directory(target).createSync(recursive: true);
        continue;
      }
      Directory(p.dirname(target)).createSync(recursive: true);
      final out = OutputFileStream(target);
      e.writeContent(out);
      out.closeSync();
    }
  } finally {
    archive.clearSync();
  }
}

/// The setup's scripts and tools must be executable on Linux.
void markExecutables(String dir) {
  if (isWindows) return;
  for (final rel in [
    'helixsr-setup.sh',
    'helixsr-uninstall.sh',
    p.join(_scalerDir, 'setup_linux.sh'),
    p.join('setup', 'lib', 'model', 'launch_synth'),
    p.join('setup', 'hlxfsr4', 'tools', 'dxc_assemble'),
  ]) {
    final f = p.join(dir, rel);
    if (fileExists(f)) {
      try {
        Process.runSync('chmod', ['755', f]);
      } catch (_) {}
    }
  }
}

// ---- build -------------------------------------------------------------

List<String> helixSr3BuildCommand(
  String release, {
  bool rebuild = false,
  String dlssPath = '',
}) {
  final dlss = dlssPath.isNotEmpty && fileExists(dlssPath);
  if (isWindows) {
    return [
      'powershell.exe',
      '-NoProfile',
      '-NonInteractive',
      '-ExecutionPolicy',
      'Bypass',
      '-File',
      p.join(release, 'helixsr-setup.ps1'),
      '-Yes',
      if (rebuild) '-Rebuild',
      if (dlss) ...['-Dlss', dlssPath],
    ];
  }
  return [
    'bash',
    p.join(release, 'helixsr-setup.sh'),
    '--yes',
    if (rebuild) '--rebuild',
    if (dlss) ...['--dlss', dlssPath],
  ];
}

Future<void> _stopTree(Process proc) async {
  try {
    if (isWindows) {
      await Process.run('taskkill', ['/T', '/F', '/PID', '${proc.pid}']);
    } else {
      // The setup runs in its own process group (setsid): stop all of it.
      await Process.run('kill', ['-TERM', '--', '-${proc.pid}']);
      proc.kill();
    }
  } catch (_) {
    proc.kill();
  }
}

/// Runs upstream's setup (--yes): it fetches Python + numpy and Microsoft's
/// shader compiler if needed, NVIDIA's DLSS 310.7.0 DLL from NVIDIA's GitHub
/// and AMD's FSR 4 driver file, and builds HLX DLSS and HLX FSR 4. Its own
/// game installer that follows is stopped before it lists any game (the
/// Manager installs games itself). True when the network is built.
Future<bool> helixSr3Build({
  required void Function(String) log,
  bool rebuild = false,
  String dlssPath = '',
}) async {
  final release = helixSr3ReleaseDir();
  if (!isHelixSr3Release(release)) {
    throw StateError('HelixSR $helixSr3Version is not downloaded yet');
  }
  markExecutables(release);
  var cmd = helixSr3BuildCommand(release, rebuild: rebuild, dlssPath: dlssPath);
  log("Running HelixSR's setup: ${cmd.join(' ')}");
  if (!isWindows && _which('setsid')) cmd = ['setsid', ...cmd];
  final proc = await Process.start(
    cmd.first,
    cmd.sublist(1),
    workingDirectory: release,
    environment: {'PYTHONUNBUFFERED': '1'},
  );
  var stopped = false;
  final done = Completer<void>();
  var open = 2;
  void closed() {
    if (--open == 0 && !done.isCompleted) done.complete();
  }

  void pump(Stream<List<int>> s) {
    s
        .transform(utf8.decoder)
        .transform(const LineSplitter())
        .listen(
          (line) {
            if (stopped) return;
            if (line.toLowerCase().contains(buildStopLine)) {
              stopped = true;
              log(
                "(HelixSR Manager installs games itself - the setup's game list is skipped)",
              );
              _stopTree(proc);
              if (!done.isCompleted) done.complete();
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
  await done.future;
  final code = await proc.exitCode.timeout(
    const Duration(seconds: 30),
    onTimeout: () {
      proc.kill(ProcessSignal.sigkill);
      return -1;
    },
  );
  final ok = helixSr3Status().networkReady;
  if (!stopped && !ok) log("HelixSR's setup exited with code $code");
  return ok;
}

bool _which(String exe) {
  final path = Platform.environment['PATH'] ?? '';
  for (final d in path.split(isWindows ? ';' : ':')) {
    if (d.isNotEmpty && fileExists(p.join(d, exe))) return true;
  }
  return false;
}

// ---- upstream's app bridge --------------------------------------------

/// Python for upstream's bridge (standard library only): upstream's portable
/// Python, else the system's.
String helixSr3Python() {
  final d = dataDir();
  if (isWindows) {
    final py = p.join(d, 'python', 'python.exe');
    return fileExists(py) ? py : 'python';
  }
  for (final c in [p.join(d, 'python', 'bin', 'python3'), '/usr/bin/python3']) {
    if (fileExists(c)) return c;
  }
  return 'python3';
}

class BridgeException implements Exception {
  BridgeException(this.message);
  final String message;
  @override
  String toString() => message;
}

/// Test hook: replaces the Python that runs the bridge.
String? bridgePythonOverride;

/// One call of upstream's app bridge; its JSON answer.
Map<String, dynamic> helixSr3Bridge(
  String command, {
  String? release,
  Map<String, String?> options = const {},
}) {
  release ??= helixSr3ReleaseDir();
  if (!isHelixSr3Release(release)) {
    throw BridgeException('HelixSR $helixSr3Version is not downloaded yet');
  }
  final args = ['-I', p.join(release, _bridge), release, command];
  options.forEach((k, v) {
    if (v != null) args.addAll(['--$k', v]);
  });
  final res = Process.runSync(
    bridgePythonOverride ?? helixSr3Python(),
    args,
    workingDirectory: release,
    stdoutEncoding: utf8,
    stderrEncoding: utf8,
  );
  Map<String, dynamic>? out;
  final lines = '${res.stdout}'.trim().split('\n').reversed;
  for (final l in lines) {
    try {
      final v = jsonDecode(l);
      if (v is Map<String, dynamic>) {
        out = v;
        break;
      }
    } catch (_) {}
  }
  if (out == null) {
    final err = '${res.stderr}${res.stdout}'.trim();
    throw BridgeException(
      err.isEmpty
          ? 'HelixSR bridge $command gave no answer'
          : err.substring(err.length > 400 ? err.length - 400 : 0),
    );
  }
  if (out['ok'] != true) {
    throw BridgeException(
      '${out['error'] ?? 'HelixSR bridge $command failed'}',
    );
  }
  return out;
}

/// Installs (updates, switches to) [GameInfo.route] (scaler / hlxfsr).
/// Returns upstream's messages.
List<String> helixSr3Install(GameInfo game) {
  final st = helixSr3Status();
  if (!st.ready(game.route)) {
    throw BridgeException(
      game.route == 'scaler'
          ? "HelixSR $helixSr3Version's network is not built yet: build it under ENGINE first."
          : 'HLX FSR 4 is not built yet: build HelixSR $helixSr3Version under ENGINE first.',
    );
  }
  final name = game.optiDllName.toLowerCase();
  final out = helixSr3Bridge(
    'install',
    release: st.releaseDir,
    options: {
      'game': game.folder,
      'way': _ways[game.route],
      if (game.route == 'scaler') 'scaler': p.join(st.releaseDir, _scalerDir),
      if (game.route == 'scaler' && scalerDllNames.contains(name))
        'scaler-name': name,
    },
  );
  final messages = [
    for (final m in (out['messages'] as List? ?? const [])) '$m',
  ];
  if (game.route == 'scaler' && scalerUnitySpoofing(game)) {
    messages.add(
      'Unity game with DLSS: GPU spoofing turned on in OptiScaler.ini',
    );
  }
  return messages;
}

/// HelixSR Scaler is upstream's OptiScaler build, and OptiScaler turns DXGI
/// GPU spoofing off for Unity games by default. A Unity game with DLSS then
/// sees an AMD / Intel GPU, never creates DLSS and uses its own upscaler, so
/// HLX DLSS never runs. Sets [Spoofing] Dxgi=true in the game's
/// OptiScaler.ini, only while it is on auto (a value the user picked in
/// HelixSR Scaler's menu stays). Upstream keeps OptiScaler.ini across
/// updates. True when written.
bool scalerUnitySpoofing(GameInfo game) {
  if (!game.unityHasDlss) return false;
  for (final d in {game.target, game.folder}) {
    if (readScalerRecord(d) == null) continue;
    final ini = p.join(d, 'OptiScaler.ini');
    if (!fileExists(ini)) return false;
    var text = readText(ini);
    final m = RegExp(
      r'^[ \t]*Dxgi[ \t]*=[ \t]*([^\r\n]*)',
      multiLine: true,
    ).firstMatch(text);
    final cur = m?.group(1)?.trim().toLowerCase() ?? '';
    if (cur.isNotEmpty && cur != 'auto') return false;
    text = setIniValue(
      text,
      'Dxgi',
      'true',
      'Spoofing',
    ).replaceFirst(RegExp(r'^Dxgi = true', multiLine: true), 'Dxgi=true');
    writeText(ini, text);
    return true;
  }
  return false;
}

void helixSr3Remove(GameInfo game) =>
    helixSr3Bridge('remove', options: {'game': game.folder});

/// An install record of upstream's FSR drop-in from HelixSR 2 on (HLX FSR 4).
bool isHelixSr3Marker(Map<String, dynamic>? data) {
  if (data == null) return false;
  if (data['upscaler'] == 'HLX FSR 4') return true;
  final m = RegExp(r'^(\d+)\.').firstMatch('${data['helixsr'] ?? ''}');
  return m != null && int.parse(m.group(1)!) >= 2;
}

/// (dll name, HelixSR Scaler version) from the game's HelixSR-Scaler.files.
(String, String?)? readScalerRecord(String exeDir) {
  final f = p.join(exeDir, scalerRecord);
  if (!fileExists(f)) return null;
  var name = 'dxgi.dll';
  String? version;
  try {
    for (final raw in readText(f).split('\n')) {
      final line = raw.trim();
      if (line.startsWith('# version=')) {
        final v = line.substring(10).trim();
        version = v.isEmpty ? null : v;
      } else if (line.startsWith('name=')) {
        name = line.substring(5).trim();
      }
    }
  } catch (_) {}
  return (name, version);
}

// ---- SHA-256 (no extra package) ----------------------------------------

/// Streaming SHA-256 (FIPS 180-4).
class Sha256 {
  static const List<int> _k = [
    0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1, //
    0x923f82a4, 0xab1c5ed5, 0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3,
    0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174, 0xe49b69c1, 0xefbe4786,
    0x0fc19dc6, 0x240ca1cc, 0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da,
    0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7, 0xc6e00bf3, 0xd5a79147,
    0x06ca6351, 0x14292967, 0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13,
    0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85, 0xa2bfe8a1, 0xa81a664b,
    0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070,
    0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a,
    0x5b9cca4f, 0x682e6ff3, 0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208,
    0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2,
  ];

  final List<int> _h = [
    0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a, //
    0x510e527f, 0x9b05688c, 0x1f83d9ab, 0x5be0cd19,
  ];
  final Uint8List _block = Uint8List(64);
  int _blockLen = 0;
  int _total = 0;
  final Uint32List _w = Uint32List(64);

  static int _rotr(int x, int n) => ((x >> n) | (x << (32 - n))) & 0xffffffff;

  void add(List<int> data) {
    _total += data.length;
    var i = 0;
    if (_blockLen > 0) {
      while (_blockLen < 64 && i < data.length) {
        _block[_blockLen++] = data[i++];
      }
      if (_blockLen < 64) return;
      _process(_block, 0);
      _blockLen = 0;
    }
    final bytes = data is Uint8List ? data : Uint8List.fromList(data);
    while (i + 64 <= bytes.length) {
      _process(bytes, i);
      i += 64;
    }
    while (i < bytes.length) {
      _block[_blockLen++] = bytes[i++];
    }
  }

  void _process(Uint8List b, int o) {
    final w = _w;
    for (var t = 0; t < 16; t++) {
      final j = o + t * 4;
      w[t] = (b[j] << 24) | (b[j + 1] << 16) | (b[j + 2] << 8) | b[j + 3];
    }
    for (var t = 16; t < 64; t++) {
      final x = w[t - 15], y = w[t - 2];
      final s0 = _rotr(x, 7) ^ _rotr(x, 18) ^ (x >> 3);
      final s1 = _rotr(y, 17) ^ _rotr(y, 19) ^ (y >> 10);
      w[t] = (w[t - 16] + s0 + w[t - 7] + s1) & 0xffffffff;
    }
    var a = _h[0], bb = _h[1], c = _h[2], d = _h[3];
    var e = _h[4], f = _h[5], g = _h[6], h = _h[7];
    for (var t = 0; t < 64; t++) {
      final s1 = _rotr(e, 6) ^ _rotr(e, 11) ^ _rotr(e, 25);
      final ch = (e & f) ^ ((~e & 0xffffffff) & g);
      final t1 = (h + s1 + ch + _k[t] + w[t]) & 0xffffffff;
      final s0 = _rotr(a, 2) ^ _rotr(a, 13) ^ _rotr(a, 22);
      final maj = (a & bb) ^ (a & c) ^ (bb & c);
      final t2 = (s0 + maj) & 0xffffffff;
      h = g;
      g = f;
      f = e;
      e = (d + t1) & 0xffffffff;
      d = c;
      c = bb;
      bb = a;
      a = (t1 + t2) & 0xffffffff;
    }
    _h[0] = (_h[0] + a) & 0xffffffff;
    _h[1] = (_h[1] + bb) & 0xffffffff;
    _h[2] = (_h[2] + c) & 0xffffffff;
    _h[3] = (_h[3] + d) & 0xffffffff;
    _h[4] = (_h[4] + e) & 0xffffffff;
    _h[5] = (_h[5] + f) & 0xffffffff;
    _h[6] = (_h[6] + g) & 0xffffffff;
    _h[7] = (_h[7] + h) & 0xffffffff;
  }

  String hexDigest() {
    final bits = _total * 8;
    final pad = <int>[0x80];
    while ((_blockLen + pad.length) % 64 != 56) {
      pad.add(0);
    }
    for (var i = 7; i >= 0; i--) {
      pad.add((bits >> (i * 8)) & 0xff);
    }
    final total = _total;
    add(pad);
    _total = total;
    final sb = StringBuffer();
    for (final v in _h) {
      sb.write(v.toRadixString(16).padLeft(8, '0'));
    }
    return sb.toString();
  }
}
