/// INSPECT panel: everything the old slide-over drawer did. Route, proxy DLL,
/// frame-generation mode, FakeNvapi, REFramework, install / uninstall,
/// OptiScaler.ini editor and logs.
library;

import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../../app/app_model.dart';
import '../../engine/engine.dart';
import '../brutal/brutal.dart';
import '../common/cfg.dart';
import '../common/game_cover.dart';
import '../common/labels.dart';

class Inspector extends StatefulWidget {
  const Inspector({super.key, required this.model, required this.game});
  final AppModel model;
  final GameInfo game;

  @override
  State<Inspector> createState() => _InspectorState();
}

enum _Pane { setup, ini, logs }

class _InspectorState extends State<Inspector> {
  _Pane pane = _Pane.setup;
  final iniController = TextEditingController();
  bool iniLoaded = false;
  String logTab = 'helixsr';

  AppModel get m => widget.model;
  GameInfo get g => widget.game;

  @override
  void dispose() {
    iniController.dispose();
    super.dispose();
  }

  Future<void> fail(String title, String message) => showBrutalDialog<void>(
    context,
    title: title,
    body: (c) => Text(message, style: c.brutal.body),
    actions: (c) => [
      BrutalButton(
        label: 'OK',
        variant: ButtonVariant.primary,
        autofocus: true,
        onPressed: () => Navigator.of(c).pop(),
      ),
    ],
  );

  Future<void> doInstall() async {
    final err = await m.install(g);
    if (err != null && mounted) await fail('Install failed', err);
  }

  Future<void> doUninstall() async {
    final err = await m.uninstall(g);
    if (err != null && mounted) await fail('Uninstall failed', err);
  }

  void loadIni() {
    if (iniLoaded) return;
    iniLoaded = true;
    iniController.text = readOptiScalerIni(g.target);
  }

  @override
  Widget build(BuildContext context) {
    final t = context.brutal;
    final busy = m.isBusy(g);
    final core = m.core;
    final built = core?.weightsBuilt ?? false;
    return SingleChildScrollView(
      child: Padding(
        padding: EdgeInsets.only(
          right: t.shadowOffset.dx,
          bottom: t.shadowOffset.dy,
        ),
        child: BrutalPanel(
          header: 'Inspect',
          headerTrailing: Text(
            g.launcher.toUpperCase(),
            style: t.small.copyWith(color: t.onHeaderBar),
          ),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              Row(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  SizedBox(
                    width: 96 * t.scale,
                    height: 144 * t.scale,
                    child: GameCover(g),
                  ),
                  SizedBox(width: t.s3),
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(
                          BrutalTokens.fileName(g.name),
                          style: t.title,
                          maxLines: 2,
                          overflow: TextOverflow.ellipsis,
                        ),
                        SizedBox(height: t.s2),
                        Wrap(
                          spacing: t.s1,
                          runSpacing: t.s1,
                          children: [for (final tag in g.tags) Tag(tag)],
                        ),
                        SizedBox(height: t.s3),
                        Sticker(
                          g.installed ? 'Active ${g.version}' : 'Not installed',
                          color: g.installed ? t.ok : t.muted,
                          fg: g.installed ? Colors.white : t.ink,
                        ),
                      ],
                    ),
                  ),
                ],
              ),
              SizedBox(height: t.s3),
              CfgSegment<_Pane>(
                options: _Pane.values,
                value: pane,
                labelOf: (p) => p.name,
                onChanged: (p) => setState(() {
                  pane = p;
                  if (p == _Pane.ini) loadIni();
                }),
              ),
              SizedBox(height: t.s3),
              switch (pane) {
                _Pane.setup => _setup(t, busy, built),
                _Pane.ini => _ini(t),
                _Pane.logs => _logs(t),
              },
            ],
          ),
        ),
      ),
    );
  }

  Widget _setup(BrutalTokens t, bool busy, bool built) {
    final choices = routeChoices(m.core);
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        KeyValueStrip([
          ('Folder', g.folder),
          ('Exe', g.exeName ?? '---'),
          ('Route', g.routeDisplay),
          ('Status', g.statusDisplay),
          if (g.appId != null) ('AppId', g.appId!),
        ]),
        SizedBox(height: t.s3),
        CfgRow(
          'Method',
          control: CfgSegment<String>(
            options: choices,
            value: choices.contains(g.route) ? g.route : choices.first,
            labelOf: routeName,
            onChanged: busy ? null : (v) => m.edit(g, (x) => x.route = v),
          ),
        ),
        if (g.route == 'optiscaler') ...[
          CfgRow(
            'Proxy DLL',
            control: CfgSegment<String>(
              options: optiDllNames,
              value: g.optiDllName,
              labelOf: (v) => v,
              onChanged: busy
                  ? null
                  : (v) => m.edit(g, (x) => x.optiDllName = v),
            ),
          ),
          CfgRow(
            'Frame gen',
            control: CfgSegment<String>(
              options: fgModes,
              value: g.fgMode,
              labelOf: fgName,
              onChanged: busy ? null : (v) => m.edit(g, (x) => x.fgMode = v),
            ),
          ),
          CfgRow(
            'FakeNvapi',
            control: CfgToggle(
              value: g.useFakeNvapi || g.fgMode.startsWith('dlssg_'),
              onChanged: busy || g.fgMode.startsWith('dlssg_')
                  ? null
                  : (v) => m.edit(g, (x) => x.useFakeNvapi = v),
            ),
          ),
        ],
        if (g.isReEngine || g.installReFramework)
          CfgRow(
            'REFramework',
            control: CfgToggle(
              value: g.installReFramework,
              onChanged: busy
                  ? null
                  : (v) => m.edit(g, (x) => x.installReFramework = v),
            ),
          ),
        if (!Platform.isWindows && g.protonLaunchOption.isNotEmpty) ...[
          SizedBox(height: t.s2),
          Text(
            'STEAM LAUNCH OPTION',
            style: t.small.copyWith(color: t.mutedText),
          ),
          SizedBox(height: t.s1),
          Row(
            children: [
              Expanded(
                child: Container(
                  padding: EdgeInsets.all(t.s2),
                  decoration: BoxDecoration(
                    color: t.panel,
                    border: Border.all(color: t.ink, width: t.borderThin),
                  ),
                  child: SelectableText(g.protonLaunchOption, style: t.small),
                ),
              ),
              SizedBox(width: t.s2),
              BrutalButton(
                label: 'Copy',
                onPressed: () => Clipboard.setData(
                  ClipboardData(text: g.protonLaunchOption),
                ),
              ),
            ],
          ),
        ],
        SizedBox(height: t.s4),
        if (!built)
          Padding(
            padding: EdgeInsets.only(bottom: t.s3),
            child: Text(
              '> network not built yet: open ENGINE and build it first',
              style: t.small.copyWith(color: t.danger),
            ),
          ),
        Wrap(
          spacing: t.s3,
          runSpacing: t.s3,
          children: [
            BrutalButton(
              label: busy ? 'Working' : (g.installed ? 'Reinstall' : 'Install'),
              icon: PixelGlyph.download,
              variant: ButtonVariant.primary,
              onPressed: busy || !built ? null : doInstall,
            ),
            if (g.appId != null)
              BrutalButton(
                label: 'Launch',
                icon: PixelGlyph.play,
                onPressed: () => launchGame(g),
              ),
            BrutalButton(
              label: 'Folder',
              icon: PixelGlyph.folder,
              onPressed: () => openFolder(g.target),
            ),
          ],
        ),
        if (g.installed) ...[
          SizedBox(height: t.s3),
          HoldToConfirm(
            label: 'Hold to uninstall',
            icon: PixelGlyph.trash,
            onConfirmed: doUninstall,
          ),
        ],
        SizedBox(height: t.s3),
        for (final l
            in m.activity.reversed
                .where((l) => l.contains(g.name))
                .take(3)
                .toList()
                .reversed)
          LogLine(l),
      ],
    );
  }

  Widget _ini(BrutalTokens t) {
    if (!File('${g.target}${Platform.pathSeparator}OptiScaler.ini')
        .existsSync()) {
      return Text(
        '> no OptiScaler.ini yet: install with the OptiScaler method first',
        style: t.body,
      );
    }
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Container(
          height: 320 * t.scale,
          padding: EdgeInsets.all(t.s2),
          decoration: BoxDecoration(
            color: t.panel,
            border: Border.all(color: t.ink, width: t.border),
          ),
          child: TextField(
            controller: iniController,
            maxLines: null,
            expands: true,
            style: t.small,
            cursorColor: t.ink,
            decoration: const InputDecoration(
              isCollapsed: true,
              border: InputBorder.none,
            ),
          ),
        ),
        SizedBox(height: t.s3),
        Wrap(
          spacing: t.s3,
          children: [
            BrutalButton(
              label: 'Save ini',
              variant: ButtonVariant.primary,
              onPressed: () {
                saveOptiScalerIni(g.target, iniController.text);
                m.log('saved OptiScaler.ini for ${g.name} ... ok');
                m.edit(g, (_) {});
              },
            ),
            BrutalButton(
              label: 'Reload',
              onPressed: () => setState(
                () => iniController.text = readOptiScalerIni(g.target),
              ),
            ),
          ],
        ),
      ],
    );
  }

  Widget _logs(BrutalTokens t) {
    final logs = readGameLogs(g);
    final text = logTab == 'helixsr' ? logs.helixsr : logs.optiscaler;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        CfgSegment<String>(
          options: const ['helixsr', 'optiscaler'],
          value: logTab,
          labelOf: (v) => '$v.log',
          onChanged: (v) => setState(() => logTab = v),
        ),
        SizedBox(height: t.s3),
        Container(
          height: 320 * t.scale,
          padding: EdgeInsets.all(t.s2),
          color: const Color(0xFF000000),
          child: SingleChildScrollView(
            reverse: true,
            child: SelectableText(
              text.isEmpty ? '> no log yet: start the game once' : text,
              style: t.small.copyWith(color: const Color(0xFFF2F2EC)),
            ),
          ),
        ),
      ],
    );
  }
}
