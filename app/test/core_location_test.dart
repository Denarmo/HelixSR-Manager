import 'dart:convert';
import 'dart:io';
import 'dart:typed_data';

import 'package:flutter_test/flutter_test.dart';
import 'package:helixsr_manager/engine/engine.dart';
import 'package:path/path.dart' as p;

/// The core's DLL; with [network] it carries the HXSRNET1 trailer.
void makeCore(String dir, {required bool network}) {
  final dll = BytesBuilder()
    ..add(utf8.encode('HelixSR 1.8.1 dll body'))
    ..add(Uint8List(64));
  if (network) {
    final tail = ByteData(32);
    for (var i = 0; i < 8; i++) {
      tail.setUint8(i, embedMagic.codeUnitAt(i));
    }
    tail.setInt64(8, 10, Endian.little);
    tail.setInt64(16, 20, Endian.little);
    dll.add(tail.buffer.asUint8List());
  }
  File(p.join(dir, dllFsr))
    ..createSync(recursive: true)
    ..writeAsBytesSync(dll.toBytes());
}

void main() {
  late Directory tmp;

  setUp(() {
    tmp = Directory.systemTemp.createTempSync('hsr_core_loc');
    dataDirOverride = p.join(tmp.path, 'data');
  });

  tearDown(() {
    dataDirOverride = null;
    tmp.deleteSync(recursive: true);
  });

  test('network built in the shared data folder is used', () {
    // The repository's helixsr_core (found from the test's working folder)
    // has no network built.
    final bundled = Core.resolve();
    expect(networkBuilt(bundled), isFalse);
    makeCore(Core.sharedCoreDir(), network: true);
    expect(Core.resolve(), Core.sharedCoreDir());
  });

  test('an unbuilt shared core does not replace the bundled one', () {
    makeCore(Core.sharedCoreDir(), network: false);
    expect(Core.resolve(), isNot(Core.sharedCoreDir()));
  });

  test('networkBuilt accepts the older separate network files', () {
    final dir = p.join(tmp.path, 'old');
    makeCore(dir, network: false);
    expect(networkBuilt(dir), isFalse);
    for (final n in networkFiles) {
      File(p.join(dir, n)).writeAsStringSync('x');
    }
    expect(networkBuilt(dir), isTrue);
  });

  test('install folder is published for the Decky plugin', () {
    if (Platform.isWindows) return;
    final app = p.join(tmp.path, 'app');
    final core = p.join(app, 'helixsr_core', 'HelixSR-$coreVersion');
    makeCore(core, network: true);
    Core.use(core);
    Core.instance.publishLocation();
    final txt = File(p.join(dataDirOverride!, 'app_dir.txt'));
    expect(txt.readAsStringSync().trim(), app);

    txt.deleteSync();
    Core.use(Core.sharedCoreDir());
    Core.instance.publishLocation();
    expect(txt.existsSync(), isFalse);
  });
}
