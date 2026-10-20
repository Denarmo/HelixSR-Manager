/// The bundled HelixSR core: where it lives, whether it carries the network
/// and which DLLs belong to HelixSR.
library;

import 'dart:convert';
import 'dart:io';
import 'dart:typed_data';

import 'package:path/path.dart' as p;

import 'constants.dart';
import 'models.dart';
import 'paths.dart';

class Core {
  Core._(this.dir);

  /// The core folder in use (HelixSR-x.y.z).
  final String dir;

  static Core? _instance;

  static Core get instance => _instance ??= Core._(_resolve());

  /// Tests and the "use another core" setting point the engine elsewhere.
  static void use(String dir) => _instance = Core._(dir);

  static String _resolve() {
    final folder = 'HelixSR-$coreVersion';
    final candidates = <String>[
      if (Platform.environment['HELIXSR_CORE'] != null)
        Platform.environment['HELIXSR_CORE']!,
      p.join(p.dirname(Platform.resolvedExecutable), 'helixsr_core', folder),
      p.join(
        p.dirname(Platform.resolvedExecutable),
        'data',
        'helixsr_core',
        folder,
      ),
      p.join(Directory.current.path, 'helixsr_core', folder),
      p.join(Directory.current.path, '..', 'helixsr_core', folder),
      p.join(Directory.current.path, '..', '..', 'helixsr_core', folder),
    ];
    for (final c in candidates) {
      final n = normalizePath(c);
      if (fileExists(p.join(n, dllFsr))) return _writable(n);
    }
    return p.join(dataDir(), 'core', folder);
  }

  /// A read-only install folder (Program Files, a squashfs, an AppImage)
  /// cannot take a network build, so the core is copied to the data folder.
  static String _writable(String dirPath) {
    try {
      final probe = File(p.join(dirPath, '.write_probe'));
      probe.writeAsStringSync('x');
      probe.deleteSync();
      return dirPath;
    } catch (_) {
      final dest = p.join(dataDir(), 'core', p.basename(dirPath));
      if (!fileExists(p.join(dest, dllFsr))) _copyTree(dirPath, dest);
      return dest;
    }
  }

  static void _copyTree(String from, String to) {
    Directory(to).createSync(recursive: true);
    for (final e in Directory(from).listSync(recursive: true)) {
      final rel = p.relative(e.path, from: from);
      if (e is Directory) {
        Directory(p.join(to, rel)).createSync(recursive: true);
      } else if (e is File) {
        Directory(p.dirname(p.join(to, rel))).createSync(recursive: true);
        e.copySync(p.join(to, rel));
      }
    }
  }

  String path(String a, [String? b, String? c]) => p.join(dir, a, b, c);

  String get fsrDll => p.join(dir, dllFsr);

  bool get exists => dirExists(dir);

  bool get dlssLoaderAvailable =>
      fileExists(p.join(dir, loaderFolder, loaderDll));

  CoreStatus status() {
    final embedded = readEmbeddedNetwork(fsrDll);
    final separate = _hasSeparateNetworkFiles();
    final wPath = p.join(dir, networkFiles[0]);
    final kPath = p.join(dir, networkFiles[1]);
    final pyOk = isWindows
        ? fileExists(p.join(dataDir(), 'python', 'python.exe'))
        : _which('python3') ||
              fileExists(p.join(dataDir(), 'python', 'bin', 'python3'));
    return CoreStatus(
      version: coreVersion,
      coreDir: dir,
      coreExists: exists,
      networkEmbedded: embedded != null,
      networkSeparate: separate,
      weightsSize: embedded?.$1 ?? (separate ? fileSize(wPath) : 0),
      kernelsSize: embedded?.$2 ?? (separate ? fileSize(kPath) : 0),
      dllSize: fileSize(fsrDll),
      hasPython: pyOk,
      dlssLoaderAvailable: dlssLoaderAvailable,
    );
  }

  bool _hasSeparateNetworkFiles() {
    for (final n in networkFiles) {
      if (fileSize(p.join(dir, n)) == 0) return false;
    }
    return true;
  }

  /// Mirrors upstream copy_network(): separate network files are deployed
  /// only when the core DLL does not carry the network (pre-1.8 builds);
  /// otherwise stale copies are removed.
  void syncNetworkFiles(String destDir) {
    if (destDir.isEmpty || !dirExists(destDir)) return;
    final embedded = readEmbeddedNetwork(fsrDll) != null;
    for (final n in networkFiles) {
      final src = p.join(dir, n);
      final dst = p.join(destDir, n);
      if (!embedded && fileExists(src)) {
        File(src).copySync(dst);
      } else if (embedded && fileExists(dst)) {
        tryDelete(dst);
      }
    }
  }
}

bool _which(String exe) {
  final path = Platform.environment['PATH'] ?? '';
  for (final d in path.split(isWindows ? ';' : ':')) {
    if (d.isNotEmpty && fileExists(p.join(d, exe))) return true;
  }
  return false;
}

/// (weightsSize, kernelsSize) when the DLL ends in the HXSRNET1 trailer.
(int, int)? readEmbeddedNetwork(String dllPath) {
  RandomAccessFile? f;
  try {
    final file = File(dllPath);
    if (!file.existsSync()) return null;
    f = file.openSync();
    final len = f.lengthSync();
    if (len <= 32) return null;
    f.setPositionSync(len - 32);
    final tail = f.readSync(32);
    if (tail.length < 32) return null;
    final magic = ascii.encode(embedMagic);
    for (var i = 0; i < magic.length; i++) {
      if (tail[i] != magic[i]) return null;
    }
    final bd = ByteData.sublistView(Uint8List.fromList(tail));
    return (bd.getInt64(8, Endian.little), bd.getInt64(16, Endian.little));
  } catch (_) {
    return null;
  } finally {
    f?.closeSync();
  }
}

bool hasEmbeddedNetwork(String dllPath) => readEmbeddedNetwork(dllPath) != null;

bool _fileContains(String path, int maxBytes, RegExp pattern) {
  RandomAccessFile? f;
  try {
    final file = File(path);
    if (!file.existsSync()) return false;
    f = file.openSync();
    final n = f.lengthSync() < maxBytes ? f.lengthSync() : maxBytes;
    final buf = f.readSync(n);
    // Latin-1 keeps every byte 1:1, so ASCII markers inside binaries survive.
    return pattern.hasMatch(latin1.decode(buf));
  } catch (_) {
    return false;
  } finally {
    f?.closeSync();
  }
}

final RegExp _versionMarker = RegExp(r'HelixSR \d+\.\d+\.\d+');
final RegExp _loaderMarker = RegExp('HelixSR DLSS loader');

/// True when the file is a HelixSR DLL (upstream helixsr_install.is_helixsr).
bool isHelixSrBinary(String path) =>
    _fileContains(path, 4 << 20, _versionMarker);

/// True when the file is HelixSR's DLSS loader (upstream is_loader).
bool isDlssLoaderBinary(String path) =>
    _fileContains(path, 1 << 20, _loaderMarker);
