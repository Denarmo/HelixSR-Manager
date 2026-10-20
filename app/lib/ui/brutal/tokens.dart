/// Brutalist design tokens, the same system as Dena.emu
/// (docs/specs/brutalist-ui.md there): graph paper, 3 px ink borders, hard
/// offset shadows, zero radius, hazard yellow for focus, electric blue for
/// the primary action, IBM Plex Mono + Archivo Black.
library;

import 'package:flutter/material.dart';

const String brutalMono = 'IBM Plex Mono';
const String brutalDisplay = 'Archivo Black';

const Color brutalHazard = Color(0xFFFFE600);
const Color brutalGold = Color(0xFFF1C40F);

enum BrutalAccent {
  hazard(brutalHazard),
  gold(brutalGold);

  const BrutalAccent(this.color);
  final Color color;

  static BrutalAccent parse(String s) =>
      s == 'gold' ? BrutalAccent.gold : BrutalAccent.hazard;
}

/// Mouse and keyboard, or the couch: console mode draws everything larger
/// and always shows focus.
enum BrutalDensity { desktop, console }

@immutable
class BrutalTokens {
  const BrutalTokens({
    required this.dark,
    required this.ground,
    required this.gridLine,
    required this.gridLineMajor,
    required this.panel,
    required this.ink,
    required this.muted,
    required this.mutedText,
    required this.focus,
    required this.primary,
    required this.danger,
    required this.ok,
    required this.headerBar,
    required this.onHeaderBar,
    this.density = BrutalDensity.desktop,
    this.scale = 1,
  });

  /// Paper: graph paper, black ink (default).
  factory BrutalTokens.paper({BrutalAccent accent = BrutalAccent.hazard}) =>
      BrutalTokens(
        dark: false,
        ground: const Color(0xFFF2F2EC),
        gridLine: const Color(0x12000000),
        gridLineMajor: const Color(0x1F000000),
        panel: const Color(0xFFFFFFFF),
        ink: const Color(0xFF000000),
        muted: const Color(0xFFCFCFC8),
        mutedText: const Color(0xFF5A5A55),
        focus: accent.color,
        primary: const Color(0xFF1F3BFF),
        danger: const Color(0xFFE10600),
        ok: const Color(0xFF00A33A),
        headerBar: const Color(0xFF000000),
        onHeaderBar: const Color(0xFFF2F2EC),
      );

  /// Ink: paper-white ink on black.
  factory BrutalTokens.ink({BrutalAccent accent = BrutalAccent.hazard}) =>
      BrutalTokens(
        dark: true,
        ground: const Color(0xFF0E0E0E),
        gridLine: const Color(0x12FFFFFF),
        gridLineMajor: const Color(0x1FFFFFFF),
        panel: const Color(0xFF000000),
        ink: const Color(0xFFF2F2EC),
        muted: const Color(0xFF3A3A36),
        mutedText: const Color(0xFFA4A49C),
        focus: accent.color,
        primary: const Color(0xFF4A63FF),
        danger: const Color(0xFFFF3B30),
        ok: const Color(0xFF2BD46A),
        headerBar: const Color(0xFFF2F2EC),
        onHeaderBar: const Color(0xFF000000),
      );

  factory BrutalTokens.forBrightness(
    Brightness b, {
    BrutalAccent accent = BrutalAccent.hazard,
  }) => b == Brightness.dark
      ? BrutalTokens.ink(accent: accent)
      : BrutalTokens.paper(accent: accent);

  final bool dark;
  final Color ground, gridLine, gridLineMajor, panel, ink, muted, mutedText;
  final Color focus, primary, danger, ok, headerBar, onHeaderBar;
  final BrutalDensity density;

  /// 1 on the desktop; console mode scales every metric and font with the
  /// window height so the UI reads from the sofa.
  final double scale;

  /// Text on [focus] is always black; on [primary] always white.
  Color get onFocus => const Color(0xFF000000);
  Color get onPrimary => const Color(0xFFFFFFFF);
  Color get shadow => ink;

  bool get console => density == BrutalDensity.console;

  BrutalTokens at(BrutalDensity d, double s) => BrutalTokens(
    dark: dark,
    ground: ground,
    gridLine: gridLine,
    gridLineMajor: gridLineMajor,
    panel: panel,
    ink: ink,
    muted: muted,
    mutedText: mutedText,
    focus: focus,
    primary: primary,
    danger: danger,
    ok: ok,
    headerBar: headerBar,
    onHeaderBar: onHeaderBar,
    density: d,
    scale: s,
  );

  // ---- metrics ----------------------------------------------------------
  double get s1 => 4 * scale;
  double get s2 => 8 * scale;
  double get s3 => 12 * scale;
  double get s4 => 16 * scale;
  double get s6 => 24 * scale;
  double get s8 => 32 * scale;
  double get border => (3 * scale).roundToDouble();
  double get borderThin => (2 * scale).roundToDouble();
  double get gridCell => 8;
  Offset get shadowOffset => Offset(4 * scale, 4 * scale).round();
  Offset get shadowOffsetLarge => Offset(6 * scale, 6 * scale).round();
  double get rowHeight => (console ? 56 : 40) * scale;
  double get buttonHeight => (console ? 48 : 38) * scale;
  double get iconSize => 18 * scale;

  static const Duration release = Duration(milliseconds: 60);

  // ---- type -------------------------------------------------------------
  TextStyle _mono(double size, double lh, FontWeight w, {double ls = 0}) =>
      TextStyle(
        fontFamily: brutalMono,
        fontSize: size * scale,
        height: lh / size,
        fontWeight: w,
        letterSpacing: ls,
        color: ink,
      );

  TextStyle _display(double size, double lh) => TextStyle(
    fontFamily: brutalDisplay,
    fontFamilyFallback: const [brutalMono],
    fontSize: size * scale,
    height: lh / size,
    fontWeight: FontWeight.w400,
    color: ink,
  );

  TextStyle get display => _display(40, 44);
  TextStyle get displaySmall => _display(28, 32);
  TextStyle get title => _mono(18, 24, FontWeight.w600);
  TextStyle get body => _mono(14, 20, FontWeight.w500);
  TextStyle get row => _mono(14, 18, FontWeight.w600);
  TextStyle get label => _mono(13, 16, FontWeight.w600, ls: 0.5);
  TextStyle get small => _mono(11, 14, FontWeight.w500);

  TextTheme get textTheme => TextTheme(
    displayLarge: display,
    displayMedium: display,
    displaySmall: displaySmall,
    headlineLarge: displaySmall,
    headlineMedium: title,
    headlineSmall: title,
    titleLarge: title,
    titleMedium: title,
    titleSmall: label,
    bodyLarge: body,
    bodyMedium: body,
    bodySmall: small,
    labelLarge: label,
    labelMedium: label,
    labelSmall: small,
  );

  BoxDecoration panelDecoration({
    Color? fill,
    bool large = false,
    bool shadowed = true,
    Color? borderColor,
  }) => BoxDecoration(
    color: fill ?? panel,
    border: Border.all(color: borderColor ?? ink, width: border),
    boxShadow: shadowed
        ? [
            BoxShadow(
              color: shadow,
              offset: large ? shadowOffsetLarge : shadowOffset,
            ),
          ]
        : null,
  );

  /// `MOONLIGHT_QUEST` style file names for tables (display only).
  static String fileName(String title) =>
      title.trim().toUpperCase().replaceAll(RegExp(r'\s+'), '_');

  ThemeData toTheme() {
    final scheme = ColorScheme(
      brightness: dark ? Brightness.dark : Brightness.light,
      primary: primary,
      onPrimary: onPrimary,
      secondary: focus,
      onSecondary: onFocus,
      error: danger,
      onError: Colors.white,
      surface: ground,
      onSurface: ink,
      outline: ink,
    );
    return ThemeData(
      useMaterial3: true,
      colorScheme: scheme,
      scaffoldBackgroundColor: ground,
      textTheme: textTheme,
      fontFamily: brutalMono,
      focusColor: focus,
      splashFactory: NoSplash.splashFactory,
      highlightColor: Colors.transparent,
      hoverColor: Colors.transparent,
      pageTransitionsTheme: const PageTransitionsTheme(
        builders: {
          TargetPlatform.linux: _Cut(),
          TargetPlatform.windows: _Cut(),
          TargetPlatform.android: _Cut(),
          TargetPlatform.macOS: _Cut(),
          TargetPlatform.iOS: _Cut(),
        },
      ),
      scrollbarTheme: ScrollbarThemeData(
        thumbColor: WidgetStatePropertyAll(ink),
        trackColor: WidgetStatePropertyAll(muted),
        radius: Radius.zero,
        thickness: WidgetStatePropertyAll(8 * scale),
      ),
      extensions: [BrutalThemeData(this)],
    );
  }
}

extension on Offset {
  Offset round() => Offset(dx.roundToDouble(), dy.roundToDouble());
}

/// Page changes are a hard cut.
class _Cut extends PageTransitionsBuilder {
  const _Cut();
  @override
  Widget buildTransitions<T>(
    PageRoute<T> route,
    BuildContext context,
    Animation<double> animation,
    Animation<double> secondaryAnimation,
    Widget child,
  ) => child;
}

class BrutalThemeData extends ThemeExtension<BrutalThemeData> {
  const BrutalThemeData(this.tokens);
  final BrutalTokens tokens;

  @override
  BrutalThemeData copyWith({BrutalTokens? tokens}) =>
      BrutalThemeData(tokens ?? this.tokens);

  @override
  BrutalThemeData lerp(BrutalThemeData? other, double t) =>
      t < 0.5 ? this : (other ?? this);
}

extension BrutalContext on BuildContext {
  BrutalTokens get brutal =>
      Theme.of(this).extension<BrutalThemeData>()?.tokens ??
      BrutalTokens.paper();
}
