/// ENGINE: HelixSR core status, GPU list and the network compiler.
library;

import 'package:flutter/material.dart';

import '../../app/app_model.dart';
import '../../app/pickers.dart';
import '../../engine/engine.dart';
import '../brutal/brutal.dart';
import '../common/labels.dart';

class EnginePage extends StatefulWidget {
  const EnginePage({super.key, required this.model});
  final AppModel model;

  @override
  State<EnginePage> createState() => _EnginePageState();
}

class _EnginePageState extends State<EnginePage> {
  String dlssPath = '';
  final scroll = ScrollController();

  AppModel get m => widget.model;

  @override
  void dispose() {
    scroll.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final t = context.brutal;
    return ListenableBuilder(
      listenable: m,
      builder: (context, _) {
        final c = m.core;
        WidgetsBinding.instance.addPostFrameCallback((_) {
          if (scroll.hasClients) scroll.jumpTo(scroll.position.maxScrollExtent);
        });
        return Padding(
          padding: EdgeInsets.all(t.s4),
          child: Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              SizedBox(
                width: 460 * t.scale,
                child: SingleChildScrollView(
                  child: Padding(
                    padding: EdgeInsets.only(
                      right: t.shadowOffsetLarge.dx,
                      bottom: t.shadowOffsetLarge.dy,
                    ),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.stretch,
                      children: [
                        BrutalPanel(
                          header: 'Core.sys',
                          headerTrailing: Text(
                            c == null
                                ? ''
                                : (c.weightsBuilt ? '[BUILT]' : '[NOT BUILT]'),
                            style: t.label.copyWith(color: t.onHeaderBar),
                          ),
                          child: c == null
                              ? Text('> reading core...', style: t.body)
                              : KeyValueStrip([
                                  ('Core', 'HelixSR ${c.version}'),
                                  ('Folder', c.coreDir),
                                  (
                                    'Network',
                                    c.networkEmbedded
                                        ? 'embedded in $dllFsr'
                                        : (c.networkSeparate
                                              ? 'separate files'
                                              : 'not built'),
                                  ),
                                  ('Weights', formatBytes(c.weightsSize)),
                                  ('Kernels', formatBytes(c.kernelsSize)),
                                  ('DLL', formatBytes(c.dllSize)),
                                  ('Python', c.hasPython ? 'found' : 'missing'),
                                  (
                                    'DLSS loader',
                                    c.dlssLoaderAvailable
                                        ? 'available'
                                        : 'missing',
                                  ),
                                ]),
                        ),
                        SizedBox(height: t.s4),
                        _helixSr3Panel(t, c?.helixSr3),
                        SizedBox(height: t.s4),
                        BrutalPanel(
                          header: 'Build.cfg',
                          child: Column(
                            crossAxisAlignment: CrossAxisAlignment.stretch,
                            children: [
                              Text(
                                '> compiles NVIDIA DLSS Model E locally into the core DLL. Uses a local nvngx_dlss.dll or downloads one. The DLSS DLL picked here is used by the HelixSR $helixSr3Version build too.',
                                style: t.small,
                              ),
                              SizedBox(height: t.s3),
                              Row(
                                children: [
                                  Expanded(
                                    child: Text(
                                      dlssPath.isEmpty
                                          ? 'DLSS DLL: auto'
                                          : dlssPath,
                                      overflow: TextOverflow.ellipsis,
                                      style: t.small,
                                    ),
                                  ),
                                  BrutalButton(
                                    label: 'Browse',
                                    icon: PixelGlyph.folder,
                                    onPressed: () async {
                                      final p = await Pickers.dlssFile();
                                      if (p != null)
                                        setState(() => dlssPath = p);
                                    },
                                  ),
                                ],
                              ),
                              SizedBox(height: t.s3),
                              Wrap(
                                spacing: t.s3,
                                runSpacing: t.s3,
                                children: [
                                  BrutalButton(
                                    label: m.building
                                        ? 'Building'
                                        : 'Build 1.8.1 network',
                                    icon: PixelGlyph.bolt,
                                    variant: ButtonVariant.primary,
                                    onPressed: m.building
                                        ? null
                                        : () => m.build(dlssPath: dlssPath),
                                  ),
                                  BrutalButton(
                                    label: 'Sync games',
                                    icon: PixelGlyph.refresh,
                                    onPressed: m.building
                                        ? null
                                        : m.syncInstalled,
                                  ),
                                  BrutalButton(
                                    label: 'Open core',
                                    icon: PixelGlyph.folder,
                                    onPressed: c == null
                                        ? null
                                        : () => openFolder(c.coreDir),
                                  ),
                                ],
                              ),
                            ],
                          ),
                        ),
                        SizedBox(height: t.s4),
                        BrutalPanel(
                          header: 'GPU',
                          child: Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              for (final g in m.gpus)
                                Text(
                                  '> ${g.name}${g.ramMb > 0 ? '  ${g.ramMb} MB' : ''}',
                                  style: t.small,
                                ),
                              if (m.gpus.isEmpty)
                                Text('> detecting...', style: t.small),
                            ],
                          ),
                        ),
                      ],
                    ),
                  ),
                ),
              ),
              SizedBox(width: t.s4),
              Expanded(
                child: Padding(
                  padding: EdgeInsets.only(
                    right: t.shadowOffsetLarge.dx,
                    bottom: t.shadowOffsetLarge.dy,
                  ),
                  child: Container(
                    decoration: BoxDecoration(
                      color: const Color(0xFF000000),
                      border: Border.all(color: t.ink, width: t.border),
                      boxShadow: [
                        BoxShadow(color: t.shadow, offset: t.shadowOffsetLarge),
                      ],
                    ),
                    padding: EdgeInsets.all(t.s3),
                    child: ListView(
                      controller: scroll,
                      children: [
                        if (m.buildLog.isEmpty)
                          Text(
                            '> compiler output appears here',
                            style: t.small.copyWith(
                              color: const Color(0xFFA4A49C),
                            ),
                          ),
                        for (final l in m.buildLog)
                          Text(
                            l,
                            style: t.small.copyWith(
                              color: const Color(0xFFF2F2EC),
                            ),
                          ),
                      ],
                    ),
                  ),
                ),
              ),
            ],
          ),
        );
      },
    );
  }

  Widget _helixSr3Panel(BrutalTokens t, HelixSr3Status? h) {
    final state = h == null
        ? ''
        : h.scalerReady
        ? '[BUILT]'
        : (h.downloaded ? '[NOT BUILT]' : '[NOT DOWNLOADED]');
    return BrutalPanel(
      header: 'HelixSR $helixSr3Version',
      headerTrailing: Text(
        state,
        style: t.label.copyWith(color: t.onHeaderBar),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Text(
            '> upstream lonewolf0622/HelixSR $helixSr3Version: HLX DLSS through HelixSR Scaler '
            '(DX12, DX11 and Vulkan games) and HLX FSR 4 (AMD\'s FSR 4 network for GPUs without it). '
            'The official release is downloaded (${formatBytes(helixSr3Size)}, checked by SHA-256) '
            'and built on this PC by its own setup, which fetches NVIDIA\'s DLSS DLL from NVIDIA\'s '
            'GitHub (NVIDIA\'s license) and AMD\'s FSR 4 driver file.',
            style: t.small,
          ),
          if (h != null) ...[
            SizedBox(height: t.s3),
            KeyValueStrip([
              ('Release', h.releaseDir),
              ('HLX DLSS', h.networkReady ? 'built' : 'not built'),
              ('HLX FSR 4', h.hlxReady ? 'built' : 'not built'),
              ('Scaler', h.scalerPresent ? 'present' : 'missing'),
            ]),
          ],
          SizedBox(height: t.s3),
          Wrap(
            spacing: t.s3,
            runSpacing: t.s3,
            children: [
              BrutalButton(
                label: m.building
                    ? 'Building'
                    : (h?.downloaded ?? false)
                    ? ((h?.scalerReady ?? false) ? 'Rebuild' : 'Build')
                    : 'Download + build',
                icon: PixelGlyph.bolt,
                variant: ButtonVariant.primary,
                onPressed: m.building
                    ? null
                    : () => m.build(dlssPath: dlssPath, release: 'helixsr3'),
              ),
              BrutalButton(
                label: 'Open release',
                icon: PixelGlyph.folder,
                onPressed: (h?.downloaded ?? false)
                    ? () => openFolder(h!.releaseDir)
                    : null,
              ),
            ],
          ),
        ],
      ),
    );
  }
}
