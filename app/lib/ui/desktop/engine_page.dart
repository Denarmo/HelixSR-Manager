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
                        BrutalPanel(
                          header: 'Build.cfg',
                          child: Column(
                            crossAxisAlignment: CrossAxisAlignment.stretch,
                            children: [
                              Text(
                                '> compiles NVIDIA DLSS Model E locally into the core DLL. Uses a local nvngx_dlss.dll or downloads one.',
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
                                        : 'Build network',
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
}
