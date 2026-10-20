import 'package:file_selector/file_selector.dart';

/// Native file/folder pickers, replaceable in tests.
class Pickers {
  Pickers._();
  static Future<String?> Function() directory = () => getDirectoryPath();
  static Future<String?> Function() dlssFile = () async {
    final f = await openFile(
      acceptedTypeGroups: const [
        XTypeGroup(label: 'DLSS', extensions: ['dll']),
      ],
    );
    return f?.path;
  };
}
