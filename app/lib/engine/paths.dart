/// Paths: the per-user data folder, path normalisation and small file
/// helpers that never throw (the engine treats a locked file as "skip").
library;

import 'dart:convert';
import 'dart:io';

import 'package:path/path.dart' as p;

bool get isWindows => Platform.isWindows;

/// %LOCALAPPDATA%\HelixSR on Windows, $XDG_DATA_HOME/HelixSR elsewhere.
/// Test hook: replaces [dataDir].
String? dataDirOverride;

String dataDir() {
  if (dataDirOverride != null) return dataDirOverride!;
  final env = Platform.environment;
  if (isWindows) {
    final base = env['LOCALAPPDATA'] ?? env['USERPROFILE'] ?? '.';
    return p.join(base, 'HelixSR');
  }
  final xdg = env['XDG_DATA_HOME'];
  if (xdg != null && xdg.isNotEmpty) return p.join(xdg, 'HelixSR');
  return p.join(env['HOME'] ?? '.', '.local', 'share', 'HelixSR');
}

String homeDir() =>
    Platform.environment['HOME'] ?? Platform.environment['USERPROFILE'] ?? '';

String normalizePath(String path) {
  if (path.isEmpty) return '';
  var s = path;
  if (!isWindows) s = s.replaceAll('\\', '/');
  s = p.normalize(p.absolute(s));
  while (s.length > 1 && (s.endsWith('/') || s.endsWith('\\'))) {
    if (isWindows && RegExp(r'^[A-Za-z]:[\\/]$').hasMatch(s)) break;
    s = s.substring(0, s.length - 1);
  }
  return s;
}

/// Case-folded, symlink-resolved key for de-duplicating folders.
String canonicalKey(String path) {
  final norm = normalizePath(path);
  if (norm.isEmpty) return '';
  try {
    final real = Directory(norm).existsSync()
        ? Directory(norm).resolveSymbolicLinksSync()
        : norm;
    return isWindows ? real.toLowerCase() : real;
  } catch (_) {
    return isWindows ? norm.toLowerCase() : norm;
  }
}

bool fileExists(String path) => File(path).existsSync();
bool dirExists(String path) => Directory(path).existsSync();

void tryDelete(String path) {
  try {
    final f = File(path);
    if (f.existsSync()) f.deleteSync();
  } catch (_) {}
}

void tryDeleteDir(String path) {
  try {
    final d = Directory(path);
    if (d.existsSync()) d.deleteSync(recursive: true);
  } catch (_) {}
}

void tryCopy(String from, String to) {
  try {
    File(from).copySync(to);
  } catch (_) {}
}

int fileSize(String path) {
  try {
    return File(path).lengthSync();
  } catch (_) {
    return 0;
  }
}

String readText(String path) =>
    utf8.decode(File(path).readAsBytesSync(), allowMalformed: true);

void writeText(String path, String text) =>
    File(path).writeAsBytesSync(utf8.encode(text));
