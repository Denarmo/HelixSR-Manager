/// Folder browser you can drive with a d-pad (the native picker needs a
/// mouse). Up/down move, A opens a folder, X adds the current one, B backs out.
library;

import 'dart:io';

import 'package:flutter/material.dart';
import 'package:path/path.dart' as p;

import '../../app/app_model.dart';
import '../../app/pad_input.dart';
import '../../engine/engine.dart';
import '../brutal/brutal.dart';
import 'console_widgets.dart';

Future<void> pickFolderConsole(BuildContext context, AppModel model) async {
  final dir = await Navigator.of(context).push<String>(
    MaterialPageRoute(builder: (_) => const ConsoleFolderPicker()),
  );
  if (dir != null) await model.addFolder(dir);
}

class ConsoleFolderPicker extends StatefulWidget {
  const ConsoleFolderPicker({super.key, this.start});
  final String? start;

  @override
  State<ConsoleFolderPicker> createState() => _ConsoleFolderPickerState();
}

class _ConsoleFolderPickerState extends State<ConsoleFolderPicker> {
  late String cwd;
  List<String> dirs = [];
  String? error;

  @override
  void initState() {
    super.initState();
    cwd = widget.start ?? _home();
    _load();
  }

  static String _home() {
    final h = homeDir();
    return h.isEmpty ? (Platform.isWindows ? r'C:\' : '/') : h;
  }

  List<String> _roots() {
    if (Platform.isWindows) {
      return [for (final l in 'CDEFGHIJ'.split('')) '$l:\\']
          .where((d) => Directory(d).existsSync())
          .toList();
    }
    return [
      '/',
      '/run/media',
      '/mnt',
      '/home',
    ].where((d) => Directory(d).existsSync()).toList();
  }

  void _load() {
    try {
      dirs =
          Directory(cwd)
              .listSync(followLinks: false)
              .whereType<Directory>()
              .map((d) => d.path)
              .where((d) => !p.basename(d).startsWith('.'))
              .toList()
            ..sort(
              (a, b) => p
                  .basename(a)
                  .toLowerCase()
                  .compareTo(p.basename(b).toLowerCase()),
            );
      error = null;
    } catch (e) {
      dirs = [];
      error = 'cannot read this folder';
    }
    setState(() {});
  }

  void _enter(String d) {
    cwd = d;
    _load();
  }

  void _up() {
    final parent = p.dirname(cwd);
    if (parent != cwd) _enter(parent);
  }

  @override
  Widget build(BuildContext context) {
    final t = context.brutal;
    return PadListener(
      onAction: (a) {
        if (a == PadAction.x) Navigator.of(context).pop(cwd);
        if (a == PadAction.y) _up();
      },
      child: Scaffold(
        body: GridPaper8(
          child: Column(
            children: [
              Container(
                color: t.headerBar,
                padding: EdgeInsets.symmetric(horizontal: t.s6, vertical: t.s3),
                child: Row(
                  children: [
                    Text(
                      'ADD FOLDER',
                      style: t.displaySmall.copyWith(color: t.focus),
                    ),
                    SizedBox(width: t.s6),
                    Expanded(
                      child: Text(
                        cwd,
                        style: t.title.copyWith(color: t.onHeaderBar),
                        overflow: TextOverflow.ellipsis,
                      ),
                    ),
                  ],
                ),
              ),
              Expanded(
                child: ListView(
                  padding: EdgeInsets.all(t.s6),
                  children: [
                    ConsoleRow(
                      label: 'Use this folder',
                      sub: cwd,
                      icon: PixelGlyph.check,
                      primary: true,
                      autofocus: true,
                      onPressed: () => Navigator.of(context).pop(cwd),
                    ),
                    SizedBox(height: t.s3),
                    ConsoleRow(
                      label: '.. up',
                      icon: PixelGlyph.up,
                      onPressed: _up,
                    ),
                    for (final r in _roots()) ...[
                      SizedBox(height: t.s3),
                      ConsoleRow(
                        label: r,
                        sub: 'drive / mount',
                        icon: PixelGlyph.chip,
                        onPressed: () => _enter(r),
                      ),
                    ],
                    if (error != null)
                      Padding(
                        padding: EdgeInsets.only(top: t.s3),
                        child: Text(
                          '> $error',
                          style: t.title.copyWith(color: t.danger),
                        ),
                      ),
                    for (final d in dirs) ...[
                      SizedBox(height: t.s3),
                      ConsoleRow(
                        label: p.basename(d),
                        icon: PixelGlyph.folder,
                        onPressed: () => _enter(d),
                      ),
                    ],
                  ],
                ),
              ),
              const BrutalHintBar(
                hints: [
                  HintItem('A', 'Open', filled: true),
                  HintItem('X', 'Use this folder'),
                  HintItem('Y', 'Up'),
                  HintItem('B', 'Cancel'),
                ],
              ),
            ],
          ),
        ),
      ),
    );
  }
}
