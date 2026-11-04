import '../../engine/engine.dart';

String routeName(String route) => switch (route) {
  'scaler' => 'HelixSR Scaler',
  'hlxfsr' => 'HLX FSR 4',
  'optiscaler' => '1.8.1 OptiScaler',
  'direct' => '1.8.1 Direct FSR',
  'dlss' => '1.8.1 DLSS Loader',
  _ => route,
};

String fgName(String mode) => switch (mode) {
  'auto' => 'Auto',
  'dlssg_xefg' => 'DLSS-G > XeFG',
  'dlssg_fsrfg' => 'DLSS-G > FSR-FG',
  'dlssg_nukems' => 'DLSS-G > Nukem',
  'optifg_fsrfg' => 'OptiFG',
  _ => mode,
};

String fsr4Name(String variant) => switch (variant) {
  'full' => 'FSR 4',
  'lite' => 'FSR 4 Lite (handheld)',
  _ => variant,
};

/// Routes offered for [g]: HelixSR 3's HelixSR Scaler first (the HLX FSR 4
/// drop-in for games with FSR 3.1), then the bundled 1.8.1 ways; the
/// experimental loader only when the core has it.
List<String> routeChoices(CoreStatus? core, [GameInfo? g]) => [
  'scaler',
  if (g == null || g.fsrTargets.isNotEmpty || g.installedRoute == 'hlxfsr')
    'hlxfsr',
  'optiscaler',
  'direct',
  if (core?.dlssLoaderAvailable ?? false) 'dlss',
];

/// What to tell the user when [route] cannot be installed yet.
String notReadyText(String route) => helixSr3Routes.contains(route)
    ? '> HelixSR $helixSr3Version not built yet: open ENGINE and download + build it first'
    : '> network not built yet: open ENGINE and build it first';

String formatBytes(int n) {
  if (n <= 0) return '0 B';
  const units = ['B', 'KB', 'MB', 'GB'];
  var v = n.toDouble();
  var i = 0;
  while (v >= 1024 && i < units.length - 1) {
    v /= 1024;
    i++;
  }
  return '${v.toStringAsFixed(i == 0 ? 0 : 1)} ${units[i]}';
}
