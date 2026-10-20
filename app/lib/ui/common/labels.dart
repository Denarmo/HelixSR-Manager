import '../../engine/engine.dart';

String routeName(String route) => switch (route) {
  'optiscaler' => 'OptiScaler',
  'direct' => 'Direct FSR 3.1',
  'dlss' => 'DLSS Loader',
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

/// Routes offered for [g]; the experimental loader only when the core has it.
List<String> routeChoices(CoreStatus? core) => [
  'optiscaler',
  'direct',
  if (core?.dlssLoaderAvailable ?? false) 'dlss',
];

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
