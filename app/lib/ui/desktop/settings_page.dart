/// SETTINGS as visible config files.
library;

import 'package:flutter/material.dart';

import '../../app/app_model.dart';
import '../../app/pickers.dart';
import '../../engine/engine.dart';
import '../brutal/brutal.dart';
import '../common/cfg.dart';

class SettingsPage extends StatelessWidget {
  const SettingsPage({super.key, required this.model});
  final AppModel model;

  @override
  Widget build(BuildContext context) {
    final t = context.brutal;
    return ListenableBuilder(
      listenable: model,
      builder: (context, _) {
        final s = model.settings;
        final two = MediaQuery.sizeOf(context).width > 1000;
        final appearance = CfgTable(
          header: 'Appearance.cfg',
          rows: [
            CfgRow(
              'Mode',
              control: CfgSegment<String>(
                options: const ['paper', 'ink', 'system'],
                value: s.theme,
                labelOf: (v) => v,
                onChanged: (v) => model.update((x) => x.theme = v),
              ),
            ),
            CfgRow(
              'Accent',
              control: CfgSegment<String>(
                options: const ['hazard', 'gold'],
                value: s.accent,
                labelOf: (v) => v,
                onChanged: (v) => model.update((x) => x.accent = v),
              ),
            ),
            CfgRow(
              'Library view',
              control: CfgSegment<String>(
                options: const ['table', 'grid'],
                value: s.libraryView,
                labelOf: (v) => v,
                onChanged: (v) => model.update((x) => x.libraryView = v),
              ),
            ),
            CfgRow(
              'Interface',
              control: CfgSegment<String>(
                options: const ['auto', 'desktop', 'console'],
                value: s.uiMode,
                labelOf: (v) => v,
                onChanged: (v) => model.update((x) => x.uiMode = v),
              ),
            ),
          ],
        );
        final library = CfgTable(
          header: 'Library.cfg',
          trailing: Text(
            '${s.customFolders.length} FOLDERS',
            style: t.small.copyWith(color: t.onHeaderBar),
          ),
          rows: [
            for (final f in s.customFolders)
              CfgRow(
                f.split(RegExp(r'[\\/]')).last,
                control: Row(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    Flexible(
                      child: Text(
                        f,
                        style: t.small,
                        overflow: TextOverflow.ellipsis,
                      ),
                    ),
                    SizedBox(width: t.s2),
                    BrutalButton(
                      label: 'Remove',
                      icon: PixelGlyph.cross,
                      onPressed: () => model.removeFolder(f),
                    ),
                  ],
                ),
              ),
            if (s.customFolders.isEmpty)
              Padding(
                padding: EdgeInsets.symmetric(vertical: t.s2),
                child: Align(
                  alignment: Alignment.centerLeft,
                  child: Text(
                    '> Steam libraries are found automatically. Add other game folders here.',
                    style: t.small,
                  ),
                ),
              ),
            SizedBox(height: t.s2),
            Align(
              alignment: Alignment.centerLeft,
              child: BrutalButton(
                label: 'Add folder',
                icon: PixelGlyph.plus,
                onPressed: () async {
                  final d = await Pickers.directory();
                  if (d != null) await model.addFolder(d);
                },
              ),
            ),
          ],
        );
        final about = CfgTable(
          header: 'About.cfg',
          rows: [
            CfgRow('Manager', control: Text('v$appVersion', style: t.label)),
            CfgRow(
              'HelixSR core',
              control: Text('v$coreVersion', style: t.label),
            ),
            CfgRow(
              'Device',
              control: Text(
                model.handheld.isHandheld
                    ? model.handheld.device.toUpperCase()
                    : 'DESKTOP',
                style: t.label,
              ),
            ),
            if (model.handheld.reason.isNotEmpty)
              CfgRow(
                'Detected',
                control: Text(model.handheld.reason, style: t.small),
              ),
            CfgRow(
              'Data folder',
              control: Text(
                dataDir(),
                style: t.small,
                overflow: TextOverflow.ellipsis,
              ),
            ),
            Padding(
              padding: EdgeInsets.only(top: t.s2),
              child: Text(
                '> unofficial, independent. Not affiliated with NVIDIA, AMD, Intel, Valve or Capcom. MIT + third-party notices.',
                style: t.small.copyWith(color: t.mutedText),
              ),
            ),
          ],
        );
        return SingleChildScrollView(
          padding: EdgeInsets.all(t.s4),
          child: two
              ? Row(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Expanded(
                      child: Column(
                        children: [
                          appearance,
                          SizedBox(height: t.s4),
                          about,
                        ],
                      ),
                    ),
                    SizedBox(width: t.s4),
                    Expanded(child: library),
                  ],
                )
              : Column(
                  children: [
                    appearance,
                    SizedBox(height: t.s4),
                    library,
                    SizedBox(height: t.s4),
                    about,
                  ],
                ),
        );
      },
    );
  }
}
