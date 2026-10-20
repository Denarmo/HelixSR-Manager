/// Persisted user settings: custom game folders, theme and UI mode.
library;

import 'dart:convert';
import 'dart:io';

import 'package:path/path.dart' as p;

import 'paths.dart';

class Settings {
  Settings({
    List<String>? customFolders,
    this.theme = 'paper',
    this.accent = 'hazard',
    this.uiMode = 'auto',
    this.libraryView = 'table',
  }) : customFolders = customFolders ?? [];

  List<String> customFolders;

  /// "paper", "ink" or "system".
  String theme;

  /// "hazard" or "gold".
  String accent;

  /// "auto" (console mode when a controller is detected), "desktop", "console".
  String uiMode;

  /// "table" or "grid" (desktop library).
  String libraryView;

  static String get path => p.join(dataDir(), 'manager.json');

  static Settings load() {
    try {
      final f = File(path);
      if (f.existsSync()) {
        final m = jsonDecode(readText(path)) as Map<String, dynamic>;
        return Settings(
          customFolders: (m['customFolders'] as List?)
              ?.map((e) => '$e')
              .toList(),
          theme: m['theme'] as String? ?? 'paper',
          accent: m['accent'] as String? ?? 'hazard',
          uiMode: m['uiMode'] as String? ?? 'auto',
          libraryView: m['libraryView'] as String? ?? 'table',
        );
      }
    } catch (_) {}
    return Settings();
  }

  void save() {
    try {
      Directory(dataDir()).createSync(recursive: true);
      writeText(
        path,
        const JsonEncoder.withIndent('  ').convert({
          'customFolders': customFolders,
          'theme': theme,
          'accent': accent,
          'uiMode': uiMode,
          'libraryView': libraryView,
        }),
      );
    } catch (_) {}
  }
}
