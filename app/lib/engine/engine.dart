/// HelixSR engine: game discovery and the install/uninstall routes.
/// Pure Dart (dart:io), no Flutter imports, so it also runs under `dart test`.
library;

export 'artwork.dart'
    show
        resolveArtwork,
        resolveAppId,
        steamArtUrls,
        normalizeGameName,
        prettifyFolderName,
        nameQueries,
        artworkFetchOverride,
        artworkNetworkEnabled,
        resetArtworkCaches;
export 'constants.dart';
export 'core.dart'
    show
        Core,
        hasEmbeddedNetwork,
        isHelixSrBinary,
        isDlssLoaderBinary,
        readEmbeddedNetwork;
export 'extras.dart' show clearShaderCache, inZoiUserSettingsPath;
export 'ini.dart';
export 'installer.dart';
export 'models.dart';
export 'paths.dart' show dataDir, dataDirOverride, homeDir, normalizePath;
export 'scanner.dart'
    show
        scanAllGames,
        scanGame,
        detectInZoi,
        detectReEngine,
        detectUnity,
        detectUnityPipeline,
        readUnityVersion;
export 'settings.dart';
export 'steam.dart' show getSteamLibraries, getSteamRoots;
export 'system.dart';
