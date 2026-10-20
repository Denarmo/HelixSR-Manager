import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:helixsr_manager/app/app.dart';
import 'package:helixsr_manager/app/app_model.dart';
import 'package:helixsr_manager/app/pad_input.dart';
import 'package:helixsr_manager/engine/engine.dart';

import 'support/fakes.dart';

Future<(AppModel, FakeEngine)> pump(
  WidgetTester tester, {
  Size size = const Size(1440, 900),
  bool console = false,
  String theme = 'paper',
  bool built = true,
}) async {
  tester.view.physicalSize = size;
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.reset);
  final engine = FakeEngine(built: built);
  final settings = Settings(
    theme: theme,
    uiMode: console ? 'console' : 'desktop',
  );
  final model = AppModel(engine: engine, settings: settings);
  await tester.pumpWidget(HelixApp(model: model, enablePad: false));
  await tester.runAsync(() => model.init());
  await tester.pump();
  return (model, engine);
}

/// Writes a screenshot of the whole app when SHOTS=dir is set.
Future<void> shot(WidgetTester tester, String name) async {
  final dir = Platform.environment['SHOTS'];
  if (dir == null) return;
  await expectLater(
    find.byType(HelixApp),
    matchesGoldenFile('${Directory(dir).absolute.path}/$name.png'),
  );
}

void main() {
  setUpAll(loadFonts);

  group('desktop', () {
    testWidgets('library table, inspector and install', (tester) async {
      final (m, engine) = await pump(tester);
      expect(find.text('CYBERPUNK_2077'), findsWidgets);
      expect(find.text('[x] ACTIVE'), findsWidgets);
      await tester.tap(find.text('ALAN_WAKE_2'));
      await tester.pump();
      expect(m.selected?.name, 'Alan Wake 2');
      await shot(tester, 'desktop-library');

      await tester.ensureVisible(find.text('INSTALL'));
      await tester.tap(find.text('INSTALL'));
      await tester.pump();
      await tester.pump();
      expect(engine.installs, ['Alan Wake 2:optiscaler:dxgi.dll:auto']);
      expect(
        m.games.firstWhere((g) => g.name == 'Alan Wake 2').installed,
        isTrue,
      );
    });

    testWidgets('changing proxy DLL and frame gen is passed to the engine', (
      tester,
    ) async {
      final (m, engine) = await pump(tester);
      await tester.tap(find.text('HOGWARTS_LEGACY'));
      await tester.pump();
      await tester.ensureVisible(find.text('WINMM.DLL'));
      await tester.tap(find.text('WINMM.DLL'));
      await tester.ensureVisible(find.text('DLSS-G > XEFG'));
      await tester.tap(find.text('DLSS-G > XEFG'));
      await tester.pump();
      await tester.ensureVisible(find.text('INSTALL'));
      await tester.tap(find.text('INSTALL'));
      await tester.pump();
      await tester.pump();
      expect(
        engine.installs.single,
        'Hogwarts Legacy:optiscaler:winmm.dll:dlssg_xefg',
      );
      expect(m.selected!.useFakeNvapi, isTrue);
    });

    testWidgets('filter and search narrow the table', (tester) async {
      final (m, _) = await pump(tester);
      await tester.tap(find.text('[ ]RE ENGINE(3)'));
      await tester.pump();
      expect(
        m.visible.map((g) => g.name),
        everyElement(
          anyOf(contains('Resident'), contains('Monster'), contains('Dragons')),
        ),
      );
      await tester.tap(find.text('[ ]ALL(9)'));
      await tester.enterText(find.byType(TextField).first, 'wukong');
      await tester.pump();
      expect(m.visible.single.name, 'Black Myth Wukong');
    });

    testWidgets('engine and settings pages', (tester) async {
      final (m, _) = await pump(tester);
      await tester.tap(find.text('ENGINE').first);
      await tester.pump();
      expect(find.text('embedded in amd_fidelityfx_dx12.dll'), findsOneWidget);
      await shot(tester, 'desktop-engine');
      await tester.tap(find.text('BUILD NETWORK'));
      await tester.pump();
      await tester.pump();
      expect(m.buildLog, contains('Build finished successfully!'));
      await tester.tap(find.text('SETTINGS').first);
      await tester.pump();
      await tester.tap(find.text('INK'));
      await tester.pump();
      expect(m.settings.theme, 'ink');
      await shot(tester, 'desktop-settings-ink');
    });

    testWidgets('narrow window opens the inspector as its own page', (
      tester,
    ) async {
      final (m, _) = await pump(tester, size: const Size(900, 700));
      await tester.tap(find.text('STARFIELD'));
      await tester.pumpAndSettle();
      expect(find.text('INSPECT'), findsOneWidget);
      expect(find.text('BACK'), findsWidgets);
      expect(m.selected?.name, 'Starfield');
    });

    testWidgets('uninstall needs a one second hold', (tester) async {
      final (m, engine) = await pump(tester);
      await tester.tap(find.text('CYBERPUNK_2077').first);
      await tester.pump();
      final hold = find.text('HOLD TO UNINSTALL');
      await tester.ensureVisible(hold);
      await tester.pump();
      final g = await tester.startGesture(tester.getCenter(hold));
      await tester.pump(const Duration(milliseconds: 400));
      await g.up();
      await tester.pump();
      expect(engine.uninstalls, isEmpty);
      final g2 = await tester.startGesture(tester.getCenter(hold));
      await tester.pump(const Duration(milliseconds: 1200));
      await g2.up();
      await tester.pump();
      await tester.pump();
      expect(engine.uninstalls, ['Cyberpunk 2077']);
      expect(m.games.first.installed, isFalse);
    });

    testWidgets('install is blocked while the network is not built', (
      tester,
    ) async {
      await pump(tester, built: false);
      await tester.tap(find.text('CYBERPUNK_2077').first);
      await tester.pump();
      expect(find.textContaining('network not built yet'), findsOneWidget);
    });
  });

  group('console', () {
    testWidgets('cover shelf, focus follows the d-pad', (tester) async {
      final (m, _) = await pump(
        tester,
        size: const Size(1280, 720),
        console: true,
      );
      expect(m.consoleMode, isTrue);
      await tester.pump();
      expect(find.text('ALAN_WAKE_2'), findsOneWidget); // NOW SELECTED
      await shot(tester, 'console-games');
      handlePadAction(tester.element(find.byType(HelixApp)), PadAction.right);
      await tester.pump();
      await tester.pump();
      expect(find.text('BLACK_MYTH_WUKONG'), findsOneWidget);
    });

    testWidgets('LB and RB switch pages', (tester) async {
      await pump(tester, size: const Size(1280, 720), console: true);
      PadBus.emit(PadAction.rb);
      await tester.pump();
      await tester.pump();
      expect(find.text('BUILD NETWORK'), findsOneWidget);
      await shot(tester, 'console-engine');
      PadBus.emit(PadAction.rb);
      await tester.pump();
      await tester.pump();
      expect(find.text('SYSTEM'), findsWidgets);
      await shot(tester, 'console-system');
      PadBus.emit(PadAction.lb);
      PadBus.emit(PadAction.lb);
      await tester.pump();
      await tester.pump();
      expect(find.text('FILTER ALL (9)'), findsOneWidget);
    });

    testWidgets('Y cycles the filter and X the sort', (tester) async {
      final (m, _) = await pump(
        tester,
        size: const Size(1280, 720),
        console: true,
      );
      PadBus.emit(PadAction.y);
      await tester.pump();
      expect(m.filter, GameFilter.installed);
      PadBus.emit(PadAction.x);
      await tester.pump();
      expect(m.sortKey, SortKey.status);
    });

    testWidgets('game screen: step values with left/right, install with A', (
      tester,
    ) async {
      final (m, engine) = await pump(
        tester,
        size: const Size(1280, 720),
        console: true,
      );
      final ctx = tester.element(find.byType(HelixApp));
      // Alan Wake 2 is first on the shelf
      handlePadAction(ctx, PadAction.accept);
      await tester.pump();
      await tester.pump();
      expect(find.text('ALAN_WAKE_2'), findsWidgets);
      await shot(tester, 'console-game');

      // down to METHOD ... then PROXY DLL, step it right
      handlePadAction(ctx, PadAction.down); // method
      await tester.pump();
      handlePadAction(ctx, PadAction.down); // proxy dll
      await tester.pump();
      handlePadAction(ctx, PadAction.right);
      await tester.pump();
      expect(m.selected!.optiDllName, 'winmm.dll');
      handlePadAction(ctx, PadAction.down); // frame gen
      await tester.pump();
      handlePadAction(ctx, PadAction.right);
      await tester.pump();
      expect(m.selected!.fgMode, 'dlssg_xefg');

      // back to INSTALL and press A
      for (var i = 0; i < 3; i++) {
        handlePadAction(ctx, PadAction.up);
        await tester.pump();
      }
      handlePadAction(ctx, PadAction.accept);
      await tester.pump();
      await tester.pump();
      expect(
        engine.installs.single,
        'Alan Wake 2:optiscaler:winmm.dll:dlssg_xefg',
      );

      // B returns to the shelf
      handlePadAction(ctx, PadAction.back);
      await tester.pumpAndSettle();
      expect(find.text('FILTER ALL (9)'), findsOneWidget);
    });

    testWidgets('uninstall holds A for a second', (tester) async {
      final (_, engine) = await pump(
        tester,
        size: const Size(1280, 720),
        console: true,
      );
      final ctx = tester.element(find.byType(HelixApp));
      for (var i = 0; i < 2; i++) {
        handlePadAction(ctx, PadAction.right); // Cyberpunk is third
        await tester.pump();
      }
      handlePadAction(ctx, PadAction.accept);
      await tester.pump();
      await tester.pump();
      // walk to the hold button: it is the last focusable
      for (var i = 0; i < 12; i++) {
        handlePadAction(ctx, PadAction.down);
        await tester.pump();
      }
      PadBus.acceptHeld.value = true;
      await tester.pump(const Duration(milliseconds: 300));
      PadBus.acceptHeld.value = false;
      await tester.pump();
      expect(engine.uninstalls, isEmpty);
      PadBus.acceptHeld.value = true;
      await tester.pump(const Duration(milliseconds: 1200));
      PadBus.acceptHeld.value = false;
      await tester.pump();
      await tester.pump();
      expect(engine.uninstalls, ['Cyberpunk 2077']);
    });

    testWidgets('first pad press switches auto mode to console', (
      tester,
    ) async {
      tester.view.physicalSize = const Size(1280, 720);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.reset);
      final model = AppModel(
        engine: FakeEngine(),
        settings: Settings(uiMode: 'auto'),
      );
      await tester.pumpWidget(HelixApp(model: model, enablePad: false));
      await tester.runAsync(() => model.init());
      await tester.pump();
      expect(model.consoleMode, isFalse);
      await tester.sendKeyEvent(LogicalKeyboardKey.f11);
      await tester.pump();
      expect(model.consoleMode, isTrue);
    });

    testWidgets('ink theme console', (tester) async {
      await pump(
        tester,
        size: const Size(1280, 720),
        console: true,
        theme: 'ink',
      );
      await shot(tester, 'console-games-ink');
    });
  });
}
