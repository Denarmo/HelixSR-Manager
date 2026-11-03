/// File names, versions and fixed lists. Same values as src/Engine.cs.
library;

/// HelixSR Manager release version.
const String appVersion = '2.0.0';

/// Bundled upstream HelixSR core version (helixsr_core/HelixSR-x.y.z).
const String coreVersion = '1.8.1';

const String dllFsr = 'amd_fidelityfx_dx12.dll';
const String dllSr = 'amd_fidelityfx_upscaler_dx12.dll';
const List<String> dllFiles = [dllSr, dllFsr];
const String ownDll = 'helixsr.dll';
const String ownSrDll = 'helixsr_upscaler.dll';
const List<String> networkFiles = [
  'helixsr_weights.bin',
  'helixsr_kernels.pak',
];
const String helixSrFolder = 'HelixSR';
const String markerFile = 'helixsr-install.json';
const String backupFolder = 'backup';
const List<String> optiDllNames = [
  'dxgi.dll',
  'winmm.dll',
  'version.dll',
  'dbghelp.dll',
  'd3d12.dll',
  'wininet.dll',
  'winhttp.dll',
  'OptiScaler.asi',
];
const String amdFsrFile = 'amd_fidelityfx_upscaler_dx12.amd.dll';
const String amdFgFile = 'amd_fidelityfx_framegeneration_dx12.dll';
const String myFsrFolder = 'my-fsr';
const String loaderFolder = 'dlss-loader';
const String loaderDll = 'dxgi.dll';
const String nvngxCoreDll = 'nvngx.dll';

/// The trailer of a one-file HelixSR DLL: "HXSRNET1" + u64 weights size +
/// u64 kernels size + u64 reserved (32 bytes).
const String embedMagic = 'HXSRNET1';

const List<String> fgModes = [
  'auto',
  'dlssg_xefg',
  'dlssg_fsrfg',
  'dlssg_nukems',
  'optifg_fsrfg',
];

/// FSR 4 model OptiScaler uses when an FSR 4 DLL is picked in-game
/// (OptiScaler route only). "full" keeps OptiScaler's default (FP8 model,
/// RDNA 4); "lite" forces the lighter INT8 model that runs on handheld APUs
/// and other RDNA 2/3 GPUs (Fsr4ForceEnableInt8 = true). Same ids as
/// FSR4_VARIANTS in the Linux edition.
const List<String> fsr4Variants = ['full', 'lite'];

/// OptiScaler.ini [FSR] Fsr4ForceEnableInt8 value for an FSR 4 variant.
String fsr4Int8IniValue(String variant) => variant == 'lite' ? 'true' : 'auto';

const String myFsrReadme =
    'Put an FSR upscaler DLL into this folder (for example FSR 4: amd_fidelityfx_upscaler_dx12.dll, any\r\n'
    'file name) and start the game again. Only for this game.\r\n'
    '\r\n'
    "In the game press Insert (OptiScaler's menu), then Upscaling tab > Upscalers > FFX Upscaler, and pick it there:\r\n"
    'it is listed by its version, for example "FSR 4.1.1". HelixSR stays the default ("FSR HelixSR (3.1.5)").\r\n'
    'FSR 4 is listed only if the DLL supports your GPU.\r\n'
    '\r\n'
    'To go back: delete the DLL from this folder.\r\n'
    '\r\n'
    'Handheld / RDNA 2-3 GPU (Steam Deck, Legion Go S, ROG Ally...): set "FSR 4 model" to "FSR 4 Lite (handheld)" in\r\n'
    'HelixSR Manager and install again. That turns on the lighter INT8 FSR 4 model (Fsr4ForceEnableInt8 in\r\n'
    'OptiScaler.ini), so FSR 4 is listed and runs on GPUs without FP8 support.\r\n';

final RegExp skipExe = RegExp(
  r'unins|setup|redist|crash|launcher|vc_?redist|dxsetup|easyanticheat|beservice|dotnet|helper|report|prereq|install|7z|ue4prereq|cefprocess|webhelper',
  caseSensitive: false,
);

const List<String> reTitles = [
  'pragmata',
  "dragon's dogma 2",
  'dragons dogma 2',
  'dd2',
  'monster hunter wilds',
  'monster hunter rise',
  'mhwilds',
  'mhrise',
  'resident evil',
  'biohazard',
  'devil may cry 5',
  'dmc5',
  'street fighter 6',
  'sf6',
  'kunitsu-gami',
  'dead rising deluxe',
  'onimusha',
  'mega man star force',
];

/// inZOI (KRAFTON, Unreal Engine 5): project name "BlueClient".
const String inZoiAppId = '2456740';
