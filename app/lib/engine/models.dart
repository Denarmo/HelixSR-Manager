/// Data types shared by the engine and the UI. Field names follow
/// src/Models.cs so the three editions describe a game the same way.
library;

import 'constants.dart';

class GameInfo {
  GameInfo({
    required this.id,
    required this.name,
    required this.folder,
    this.launcher = 'Custom',
    this.appId,
  });

  final String id;
  String name;
  String folder;
  String? exeFolder;
  String? exeName;
  String launcher;
  String? appId;
  String? localCoverPath;
  String? remoteCoverUrl;
  String? localHeroPath;
  String? remoteHeroUrl;
  List<String> inputs = [];
  List<String> fsrTargets = [];
  String? foundNvngxDlssPath;
  String? foundFfxFgPath;
  String? foundXeFgPath;
  String? foundXeLlPath;
  bool hasDlssG = false;

  /// "auto", "dlssg_xefg", "dlssg_fsrfg", "dlssg_nukems", "optifg_fsrfg".
  String fgMode = 'auto';

  /// "optiscaler", "direct" or "dlss" (experimental HelixSR DLSS loader).
  String route = 'optiscaler';

  /// One of [optiDllNames].
  String optiDllName = 'dxgi.dll';
  bool useFakeNvapi = true;
  bool installReFramework = false;
  bool installed = false;
  String version = coreVersion;
  bool hasBackups = false;
  bool hasLogs = false;
  bool hasMyFsr = false;
  bool isReEngine = false;
  bool isInZoi = false;

  /// Unity profile ([detectUnity]); null when the game is not a Unity game.
  UnityInfo? unity;
  bool get isUnity => unity != null;

  /// The folder HelixSR files go into.
  String get target => exeFolder ?? folder;

  String get routeDisplay {
    switch (route) {
      case 'direct':
        return 'Direct FSR 3.1';
      case 'dlss':
        return 'DLSS Loader (Experimental)';
      case 'optiscaler':
        final dll = optiDllName.isEmpty ? 'dxgi.dll' : optiDllName;
        var s = 'OptiScaler ($dll)';
        final fg = fgModeTag(fgMode);
        if (fg.isNotEmpty) s += ' + $fg';
        return s;
    }
    return 'Auto';
  }

  String get statusDisplay => installed ? 'Active ($version)' : 'Not Installed';

  /// Steam launch option that makes Proton load the proxy DLLs
  /// (mirrors compute_proton_launch_option in the Linux edition).
  String get protonLaunchOption {
    final dlls = <String>[];
    if (route == 'optiscaler') {
      final opti = optiDllName.isEmpty ? 'dxgi.dll' : optiDllName;
      if (opti.toLowerCase().endsWith('.dll')) {
        dlls.add(opti.substring(0, opti.length - 4));
      }
    } else if (route == 'dlss') {
      dlls.add(loaderDll.substring(0, loaderDll.length - 4));
    }
    if (installReFramework && !dlls.contains('dinput8')) dlls.add('dinput8');
    if (dlls.isEmpty) return '';
    return 'WINEDLLOVERRIDES="${dlls.join(',')}=n,b" %command%';
  }

  List<String> get tags => [
    ...inputs,
    if (isReEngine) 'RE ENGINE',
    if (isInZoi) 'INZOI',
    if (isUnity) 'UNITY',
  ];
}

/// What [detectUnity] learned about a Unity game.
class UnityInfo {
  const UnityInfo({
    this.version,
    this.backend,
    this.pipeline,
    this.hasD3D12 = false,
    this.hasBepInEx = false,
  });

  /// Engine version from the player's header, e.g. "6000.0.23f1".
  final String? version;

  /// "Mono" or "IL2CPP".
  final String? backend;

  /// "Built-in", "URP" or "HDRP".
  final String? pipeline;

  /// The build ships Unity's D3D12 player (`D3D12\D3D12Core.dll`).
  final bool hasD3D12;
  final bool hasBepInEx;

  /// e.g. "Unity 6 · IL2CPP · URP".
  String get summary => [
    formatUnityVersion(version),
    ?backend,
    ?pipeline,
    if (hasD3D12) 'D3D12',
  ].join(' \u00B7 ');
}

/// "6000.0.23f1" -> "Unity 6", "6000.1.2f1" -> "Unity 6.1", "2022.3.10f1" -> "Unity 2022.3".
String formatUnityVersion(String? version) {
  if (version == null || version.isEmpty) return 'Unity';
  final parts = version.split('.');
  final major = parts.length < 2 ? null : int.tryParse(parts[0]);
  if (major == null) return 'Unity $version';
  if (major >= 6000) {
    final unity = major ~/ 1000;
    return parts[1] == '0' ? 'Unity $unity' : 'Unity $unity.${parts[1]}';
  }
  return 'Unity ${parts[0]}.${parts[1]}';
}

String fgModeTag(String mode) {
  switch (mode) {
    case 'dlssg_xefg':
      return 'XeFG';
    case 'dlssg_fsrfg':
      return 'FSR-FG';
    case 'dlssg_nukems':
      return 'NukemFG';
    case 'optifg_fsrfg':
      return 'OptiFG';
  }
  return '';
}

class CoreStatus {
  const CoreStatus({
    required this.version,
    required this.coreDir,
    required this.coreExists,
    required this.networkEmbedded,
    required this.networkSeparate,
    required this.weightsSize,
    required this.kernelsSize,
    required this.dllSize,
    required this.hasPython,
    required this.dlssLoaderAvailable,
  });

  final String version;
  final String coreDir;
  final bool coreExists;

  /// HelixSR 1.8+: the network is appended to amd_fidelityfx_dx12.dll.
  final bool networkEmbedded;
  final bool networkSeparate;
  final int weightsSize;
  final int kernelsSize;
  final int dllSize;
  final bool hasPython;
  final bool dlssLoaderAvailable;

  bool get weightsBuilt => networkEmbedded || networkSeparate;
}

class GpuInfo {
  const GpuInfo(this.name, {this.ramMb = 0, this.driver = 'N/A'});
  final String name;
  final int ramMb;
  final String driver;
}

class HandheldInfo {
  const HandheldInfo({
    this.isHandheld = false,
    this.isControllerDetected = false,
    this.isSteamOs = false,
    this.isBazzite = false,
    this.reason = '',
    this.device = '',
  });
  final bool isHandheld;
  final bool isControllerDetected;
  final bool isSteamOs;
  final bool isBazzite;
  final String reason;
  final String device;
}

class ManifestInfo {
  const ManifestInfo(this.appId, this.name, this.installDir, this.libraryRoot);
  final String appId;
  final String name;
  final String installDir;
  final String libraryRoot;
}
