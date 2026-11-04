import {
  ButtonItem,
  ConfirmModal,
  DropdownItem,
  Field,
  PanelSection,
  PanelSectionRow,
  Router,
  showModal,
  Spinner,
  staticClasses,
  ToggleField,
} from "@decky/ui";
import { callable, definePlugin, toaster } from "@decky/api";
import { useEffect, useMemo, useRef, useState } from "react";
import { FaBolt } from "react-icons/fa";
import { addTracked, applyOverrides, LaunchRecord, overridesFrom, restoreTracked } from "./launchOptions";

// ---------------------------------------------------------------------------
// Backend (main.py)
// ---------------------------------------------------------------------------

type Route = "optiscaler" | "direct" | "dlss";
type Method = Route | "fsr4lite";

interface Game {
  id: string;
  name: string;
  folder: string;
  exeFolder?: string;
  appId?: string | null;
  launcher: string;
  route: Route;
  routeDisplay: string;
  optiDllName?: string;
  useFakeNvapi?: boolean;
  fgMode?: string;
  hasDlssG?: boolean;
  isReEngine?: boolean;
  isInZoi?: boolean;
  isUnity?: boolean;
  installReFramework?: boolean;
  installed: boolean;
  version?: string | null;
  inputs?: string[];
  protonLaunchOptions?: string;
  fsr4Variant?: string | null;
  lite?: LiteGame;
  native?: string | null;
}

interface LiteVerification {
  active: boolean;
  state?: string;
  checks?: Record<string, boolean>;
  missing?: string[];
  provider?: { dll: string; name: string } | null;
  model?: string | null;
  dispatches?: number;
  input?: string | null;
  output?: string | null;
  checkedAt?: number;
  message?: string;
}

interface LiteGame {
  installed: boolean;
  mode?: "lite" | "fallback";
  proxy?: string;
  label?: string;
  launchOverride?: string;
  launchOptions?: string;
  verification?: LiteVerification | null;
  eligible: boolean;
  reasons: string[];
  inputs: string[];
  inputsKnown: boolean;
}

interface LiteStatus {
  runtime: {
    ready: boolean;
    optiscaler: string;
    optiscalerBuild: string;
    payloadSize: number;
    providers: Record<string, { file: string; has412?: boolean; hasLiteModel?: boolean; providerVersions?: string[]; fileVersion?: string }>;
  };
  device: { cpu: string; amdGpu: boolean; preferLite: boolean };
  error?: string;
}

interface Option {
  id: string;
  label: string;
}

interface Status {
  success?: boolean;
  error?: string;
  version: string;
  appVersion: string;
  coreExists: boolean;
  coreDir: string;
  coreSource: string;
  weightsBuilt: boolean;
  networkEmbedded: boolean;
  building: boolean;
  capabilities: {
    fsr4Variants: Option[];
    dlssLoader: boolean;
    optiDlls: string[];
    fgModes: Option[];
  };
}

interface Result {
  success?: boolean;
  error?: string;
  message?: string;
  game?: Game;
}

interface BuildState {
  state: "idle" | "running" | "done" | "failed";
  error?: string | null;
  log: string[];
}

interface Settings {
  autoLaunchOptions?: boolean;
  launchOverrides?: Record<string, string[]>;
  liteLaunch?: Record<string, LaunchRecord & { dll: string }>;
  lastFolder?: string | null;
  [k: string]: unknown;
}

const getStatus = callable<[], Status>("get_status");
const listGames = callable<[refresh: boolean], { games?: Game[]; error?: string }>("list_games");
const findApp = callable<[appId: string], { game: Game | null; error?: string }>("find_app");
const installGame = callable<[folder: string, options: Record<string, unknown>], Result>("install");
const uninstallGame = callable<[folder: string], Result>("uninstall");
const clearCache = callable<[folder: string], Result & { cleared?: boolean }>("clear_cache");
const getSettings = callable<[], Settings>("get_settings");
const setSettings = callable<[settings: Settings], Settings>("set_settings");
const startBuild = callable<[], Result>("start_build");
const buildStatus = callable<[], BuildState>("build_status");
const liteStatus = callable<[], LiteStatus>("lite_status");
const litePrepare = callable<[], Result & { runtime?: LiteStatus["runtime"] }>("lite_prepare");
const liteInstall = callable<[folder: string, proxy: string, mode: string], Result>("lite_install");
const liteUninstall = callable<[folder: string], Result>("lite_uninstall");
const liteMode = callable<[folder: string, mode: string], Result>("lite_mode");
const liteVerify = callable<[folder: string], Result & { verification?: LiteVerification }>("lite_verify");

// The Quick Access panel can be unmounted and mounted again (for example around a dropdown menu), which
// would reset React state. The picked game lives here so the choice sticks.
let pickedFolder: string | null = null;

// ---------------------------------------------------------------------------
// Steam launch options
// ---------------------------------------------------------------------------

function readLaunchOptions(appId: number): Promise<string> {
  return new Promise((resolve) => {
    const cached = window.appDetailsStore?.GetAppDetails?.(appId)?.strLaunchOptions;
    if (typeof cached === "string") return resolve(cached);
    let done = false;
    let reg: { unregister(): void } | undefined;
    const finish = (v: string) => {
      if (done) return;
      done = true;
      reg?.unregister();
      resolve(v);
    };
    try {
      reg = SteamClient.Apps.RegisterForAppDetails(appId, (d) => finish(d?.strLaunchOptions ?? ""));
    } catch {
      finish("");
    }
    setTimeout(() => finish(""), 2000);
  });
}

/** Points the game's launch options at HelixSR's DLLs. Returns the new options, or null for non-Steam games. */
async function syncLaunchOptions(game: Game, settings: Settings): Promise<{ options: string; settings: Settings } | null> {
  if (!game.appId) return null;
  const appId = Number(game.appId);
  if (!Number.isFinite(appId) || appId <= 0) return null;
  const previous = settings.launchOverrides?.[game.appId] ?? [];
  const wanted = game.installed ? overridesFrom(game.protonLaunchOptions) : [];
  const current = await readLaunchOptions(appId);
  const next = applyOverrides(current, wanted, previous.filter((d) => !wanted.includes(d)));
  if (next !== current) SteamClient.Apps.SetAppLaunchOptions(appId, next);
  const overrides = { ...(settings.launchOverrides ?? {}) };
  if (wanted.length) overrides[game.appId] = wanted;
  else delete overrides[game.appId];
  const saved = await setSettings({ launchOverrides: overrides });
  return { options: next, settings: saved };
}

/** FSR 4 Lite: adds the proxy override and remembers the original options, so uninstall restores them exactly. */
async function liteLaunchOn(game: Game, dll: string, settings: Settings): Promise<Settings | null> {
  if (!game.appId || !(Number(game.appId) > 0)) return null;
  const appId = Number(game.appId);
  const all = { ...(settings.liteLaunch ?? {}) };
  const prior = all[game.appId];
  let current = await readLaunchOptions(appId);
  if (prior && prior.dll !== dll) {
    current = restoreTracked(current, prior);
  }
  const rec = addTracked(current, [dll], prior && prior.dll === dll ? prior : null);
  if (prior && prior.dll !== dll) rec.original = prior.original;
  if (rec.applied !== (await readLaunchOptions(appId))) SteamClient.Apps.SetAppLaunchOptions(appId, rec.applied);
  all[game.appId] = { ...rec, dll };
  return await setSettings({ liteLaunch: all });
}

async function liteLaunchOff(game: Game, settings: Settings): Promise<Settings | null> {
  if (!game.appId) return null;
  const all = { ...(settings.liteLaunch ?? {}) };
  const rec = all[game.appId];
  if (!rec) return null;
  const appId = Number(game.appId);
  const current = await readLaunchOptions(appId);
  const next = restoreTracked(current, rec);
  if (next !== current) SteamClient.Apps.SetAppLaunchOptions(appId, next);
  delete all[game.appId];
  return await setSettings({ liteLaunch: all });
}

// ---------------------------------------------------------------------------
// UI
// ---------------------------------------------------------------------------

const LITE_METHOD = { id: "fsr4lite" as Method, label: "FSR 4 Lite (AMD 4.1.2 INT8, OptiScaler 10)" };

const ROUTES: { id: Route; label: string }[] = [
  { id: "optiscaler", label: "OptiScaler (DLSS / XeSS / FSR games)" },
  { id: "direct", label: "Direct FSR 3.1 replacement" },
  { id: "dlss", label: "DLSS Loader (experimental)" },
];

function notify(title: string, body: string) {
  toaster.toast({ title, body });
}

function Content() {
  const [status, setStatus] = useState<Status | null>(null);
  const [games, setGames] = useState<Game[]>([]);
  const [settings, setLocalSettings] = useState<Settings>({});
  const [folder, setFolderState] = useState<string | null>(pickedFolder);
  const setFolder = (f: string | null) => {
    pickedFolder = f;
    setFolderState(f);
  };
  const [lite, setLite] = useState<LiteStatus | null>(null);
  const [runningFolder, setRunningFolder] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [build, setBuild] = useState<BuildState | null>(null);

  // Per-install choices, reset whenever another game is picked.
  const [route, setRoute] = useState<Method>("optiscaler");
  const [liteProxy, setLiteProxy] = useState("dxgi.dll");
  const [optiDll, setOptiDll] = useState("dxgi.dll");
  const [fgMode, setFgMode] = useState("auto");
  const [fakeNvapi, setFakeNvapi] = useState(true);
  const [reframework, setReframework] = useState(false);

  const game = useMemo(() => games.find((g) => g.folder === folder) ?? null, [games, folder]);
  const caps = status?.capabilities;
  const autoLaunch = settings.autoLaunchOptions !== false;
  const mounted = useRef(true);

  const upsertGame = (g: Game) => {
    setGames((list) => {
      const i = list.findIndex((x) => x.folder === g.folder);
      if (i < 0) return [...list, g].sort((a, b) => a.name.localeCompare(b.name));
      const copy = list.slice();
      copy[i] = g;
      return copy;
    });
  };

  const loadGames = async (refresh: boolean) => {
    const res = await listGames(refresh);
    if (res.error) throw new Error(res.error);
    if (mounted.current) setGames(res.games ?? []);
    return res.games ?? [];
  };

  useEffect(() => {
    mounted.current = true;
    (async () => {
      try {
        const [st, cfg] = await Promise.all([getStatus(), getSettings()]);
        if (st.error) throw new Error(st.error);
        setStatus(st);
        setLocalSettings(cfg ?? {});
        liteStatus().then((l) => mounted.current && !l.error && setLite(l)).catch(() => undefined);
        if (st.building) setBuild({ state: "running", log: [] });
        const list = await loadGames(false);
        const app = Router.MainRunningApp;
        if (app?.appid) {
          const res = await findApp(String(app.appid));
          if (res.game) {
            upsertGame(res.game);
            setRunningFolder(res.game.folder);
            // The running game is picked unless the user already picked one this session.
            if (!pickedFolder) setFolder(res.game.folder);
            return;
          }
        }
        const fresh = list.length ? list : await loadGames(true);
        if (!pickedFolder && cfg?.lastFolder && fresh.some((g) => g.folder === cfg.lastFolder)) setFolder(cfg.lastFolder);
      } catch (e) {
        setError(String(e));
      }
    })();
    return () => {
      mounted.current = false;
    };
  }, []);

  // Reset the options to what the selected game has (or sensible defaults).
  useEffect(() => {
    if (!game) return;
    const helixRoute: Route = game.route === "dlss" && !caps?.dlssLoader ? "optiscaler" : game.route;
    const preferLite = !!lite?.device.preferLite && !!game.lite?.eligible && !game.installed;
    setRoute(game.lite?.installed || preferLite ? "fsr4lite" : helixRoute);
    setLiteProxy(game.lite?.proxy || "dxgi.dll");
    setOptiDll(game.optiDllName || "dxgi.dll");
    setFgMode(game.fgMode || "auto");
    setFakeNvapi(game.useFakeNvapi !== false);
    setReframework(!!(game.installReFramework || game.isReEngine));
  }, [game?.folder, game?.installed, game?.lite?.installed, caps, lite?.device.preferLite]);

  // Remember the last picked game across Quick Access openings.
  useEffect(() => {
    if (folder && folder !== settings.lastFolder) setSettings({ lastFolder: folder }).then((s) => mounted.current && setLocalSettings(s));
  }, [folder]);

  // Poll the network build while it runs.
  useEffect(() => {
    if (build?.state !== "running") return;
    const t = setInterval(async () => {
      const st = await buildStatus();
      if (!mounted.current) return;
      setBuild(st);
      if (st.state !== "running") {
        setStatus(await getStatus());
        notify("HelixSR", st.state === "done" ? "Network built. You can install HelixSR now." : st.error || "Build failed");
      }
    }, 2000);
    return () => clearInterval(t);
  }, [build?.state]);

  const run = async (label: string, fn: () => Promise<void>) => {
    setBusy(label);
    setError(null);
    try {
      await fn();
    } catch (e) {
      setError(String(e instanceof Error ? e.message : e));
    } finally {
      if (mounted.current) setBusy(null);
    }
  };

  const applyLaunch = async (g: Game) => {
    if (!autoLaunch) return;
    try {
      const res = await syncLaunchOptions(g, settings);
      if (res) setLocalSettings(res.settings);
    } catch (e) {
      notify("HelixSR", `Could not set launch options: ${e}`);
    }
  };

  const doInstall = () =>
    run("install", async () => {
      if (!game) return;
      const opts: Record<string, unknown> = { route };
      if (route === "optiscaler") {
        opts.optiDll = optiDll;
        opts.fgMode = fgMode;
        opts.useFakeNvapi = fakeNvapi || fgMode.startsWith("dlssg_");
      }
      if (game.isReEngine) opts.installReFramework = reframework;
      const res = await installGame(game.folder, opts);
      if (!res.success) throw new Error(res.error || res.message || "Install failed");
      if (res.game) {
        upsertGame(res.game);
        await applyLaunch(res.game);
      }
      notify("HelixSR", res.message || `Installed for ${game.name}`);
    });

  const doUninstall = () =>
    run("uninstall", async () => {
      if (!game) return;
      const res = await uninstallGame(game.folder);
      if (!res.success) throw new Error(res.error || "Uninstall failed");
      if (res.game) {
        upsertGame(res.game);
        await applyLaunch(res.game);
      }
      notify("HelixSR", res.message || `Removed from ${game.name}`);
    });

  const doClearCache = () =>
    run("cache", async () => {
      if (!game) return;
      const res = await clearCache(game.folder);
      if (res.success === false) throw new Error(res.error || "Could not clear the shader cache");
      notify("HelixSR", res.cleared === false ? "No shader cache found" : "Shader cache cleared");
    });

  // ----- FSR 4 Lite -----

  const doLitePrepare = () =>
    run("lite-prepare", async () => {
      const res = await litePrepare();
      if (!res.success) throw new Error(res.error || "Could not get the FSR 4 Lite runtime");
      setLite(await liteStatus());
      notify("FSR 4 Lite", "Runtime downloaded and checked: AMD provider 4.1.2 with the INT8 Lite model");
    });

  const liteEnable = async (g: Game) => {
    const res = await liteInstall(g.folder, liteProxy, "lite");
    if (!res.success) throw new Error(res.error || "Could not enable FSR 4 Lite");
    if (res.game) {
      upsertGame(res.game);
      if (autoLaunch && res.game.lite?.launchOverride) {
        const saved = await liteLaunchOn(res.game, res.game.lite.launchOverride, settings);
        if (saved) setLocalSettings(saved);
      }
    }
    notify("FSR 4 Lite", `Enabled for ${g.name}. Start the game and turn on its DLSS, XeSS or FSR.`);
  };

  const doLiteEnable = () => {
    if (!game) return;
    if (!game.installed) {
      run("lite-install", () => liteEnable(game));
      return;
    }
    showModal(
      <ConfirmModal
        strTitle="Switch to FSR 4 Lite"
        strDescription={
          `HelixSR is installed in ${game.name} and also uses OptiScaler, so it has to come out first. ` +
          "Disabling FSR 4 Lite later does not put HelixSR back; you can reinstall it from here."
        }
        strOKButtonText="Remove HelixSR and enable Lite"
        onOK={() =>
          run("lite-install", async () => {
            const un = await uninstallGame(game.folder);
            if (!un.success) throw new Error(un.error || "Could not remove HelixSR");
            if (un.game) {
              upsertGame(un.game);
              await applyLaunch(un.game);
              await liteEnable(un.game);
            }
          })
        }
      />,
    );
  };

  const doLiteDisable = () =>
    run("lite-uninstall", async () => {
      if (!game) return;
      const res = await liteUninstall(game.folder);
      if (!res.success) throw new Error(res.error || "Could not disable FSR 4 Lite");
      if (res.game) upsertGame(res.game);
      const saved = await liteLaunchOff(game, settings);
      if (saved) setLocalSettings(saved);
      notify("FSR 4 Lite", `Removed from ${game.name}; files and launch options restored`);
    });

  const doLiteMode = (fallback: boolean) =>
    run("lite-mode", async () => {
      if (!game) return;
      const res = await liteMode(game.folder, fallback ? "fallback" : "lite");
      if (!res.success) throw new Error(res.error || "Could not switch");
      if (res.game) upsertGame(res.game);
      notify("FSR 4 Lite", fallback ? "Fallback on: OptiScaler's built-in FSR 2.2 on the next launch" : "FSR 4 Lite on the next launch");
    });

  const doLiteVerify = () =>
    run("lite-verify", async () => {
      if (!game) return;
      const res = await liteVerify(game.folder);
      if (!res.success) throw new Error(res.error || "Could not read the OptiScaler log");
      if (res.game) upsertGame(res.game);
      const v = res.verification;
      if (!v) return;
      if (v.active) notify("FSR 4 Lite", `Active: ${v.provider?.name ?? "4.1.2"} INT8 Lite, ${v.input} to ${v.output}`);
      else notify("FSR 4 Lite", v.message || `Not verified: ${(v.missing ?? []).join(", ") || "no data"}`);
    });

  const doBuild = () =>
    showModal(
      <ConfirmModal
        strTitle="Build the HelixSR network"
        strDescription={
          "HelixSR builds its network on this device from NVIDIA's DLSS 310.7.0 DLL (taken from one of your games, " +
          "or downloaded from NVIDIA's GitHub, which means you accept NVIDIA's license). " +
          "It also downloads Python and Microsoft's shader compiler once. This takes several minutes; keep the device plugged in."
        }
        strOKButtonText="Build"
        onOK={async () => {
          const res = await startBuild();
          if (!res.success) {
            setError(res.error || "Could not start the build");
            return;
          }
          setBuild({ state: "running", log: [] });
        }}
      />,
    );

  const toggleAutoLaunch = async (v: boolean) => {
    setLocalSettings(await setSettings({ autoLaunchOptions: v }));
  };

  if (!status && !error) {
    return (
      <PanelSection>
        <PanelSectionRow>
          <Spinner style={{ width: "100%", height: 32 }} />
        </PanelSectionRow>
      </PanelSection>
    );
  }

  const renderLite = (g: Game) => {
    const rt = lite?.runtime;
    const lg = g.lite;
    const v = lg?.verification;
    const prov = rt?.providers ?? {};
    const provLine = Object.values(prov)
      .map((p) => `${p.file} ${p.fileVersion ?? ""}${p.has412 ? " · 4.1.2" : ""}${p.hasLiteModel ? " · INT8 Lite" : ""}`)
      .join(" / ");
    let statusText = "Not enabled";
    if (lg?.installed) {
      if (lg.mode === "fallback") statusText = "Fallback: OptiScaler's built-in FSR 2.2";
      else if (v?.active) statusText = `Active · ${v.provider?.name ?? "FSR 4.1.2"} · ${v.model} · ${v.input} → ${v.output}`;
      else if (v) statusText = `Enabled, not verified (${(v.missing ?? []).join(", ") || v.message || "no data"})`;
      else statusText = "Enabled, not verified yet";
    }
    return (
      <>
        <PanelSectionRow>
          <Field label="FSR 4 Lite" description={statusText} focusable={false} />
        </PanelSectionRow>
        {!rt?.ready ? (
          <PanelSectionRow>
            <ButtonItem
              layout="below"
              disabled={!!busy || !lite}
              description={`OptiScaler ${rt?.optiscaler ?? "10.0.0-pre1"} and AMD's driver FSR 4 providers, from the pinned Decky OptiScaler v0.0.9 release. Every file is checked by SHA-256.`}
              onClick={doLitePrepare}
            >
              {busy === "lite-prepare" ? "Downloading and checking..." : `Download runtime (${Math.round((rt?.payloadSize ?? 108e6) / 1e6)} MB)`}
            </ButtonItem>
          </PanelSectionRow>
        ) : (
          <PanelSectionRow>
            <Field label="Provider" description={provLine} focusable={false} />
          </PanelSectionRow>
        )}
        {!lg?.installed ? (
          <>
            <PanelSectionRow>
              <DropdownItem
                label="OptiScaler proxy DLL"
                description="If another mod already uses this name, the next free one is taken."
                rgOptions={["dxgi.dll", "winmm.dll", "version.dll", "dbghelp.dll", "wininet.dll", "winhttp.dll"].map((d) => ({ data: d, label: d }))}
                selectedOption={liteProxy}
                onChange={(o) => setLiteProxy(o.data)}
              />
            </PanelSectionRow>
            <PanelSectionRow>
              <ButtonItem layout="below" disabled={!rt?.ready || !!busy || !lg?.eligible} onClick={doLiteEnable}>
                {busy === "lite-install" ? "Enabling..." : g.installed ? "Remove HelixSR and enable FSR 4 Lite" : "Enable FSR 4 Lite"}
              </ButtonItem>
            </PanelSectionRow>
            {lg && !lg.inputsKnown && lg.eligible && (
              <PanelSectionRow>
                <div style={{ fontSize: 11, opacity: 0.7 }}>
                  No DLSS, XeSS or FSR DLL found in the folder. Lite only works if the game has a temporal upscaler of its own.
                </div>
              </PanelSectionRow>
            )}
          </>
        ) : (
          <>
            <PanelSectionRow>
              <ButtonItem layout="below" disabled={!!busy} onClick={doLiteVerify}>
                {busy === "lite-verify" ? "Reading the log..." : "Check what ran"}
              </ButtonItem>
            </PanelSectionRow>
            <PanelSectionRow>
              <ToggleField
                label="Use fallback (FSR 2.2)"
                description="If Lite does not run or looks wrong: OptiScaler's built-in FSR 2.2, no AMD DLL needed."
                checked={lg.mode === "fallback"}
                disabled={!!busy}
                onChange={doLiteMode}
              />
            </PanelSectionRow>
            <PanelSectionRow>
              <ButtonItem layout="below" disabled={!!busy} onClick={doLiteDisable}>
                {busy === "lite-uninstall" ? "Removing..." : "Disable FSR 4 Lite (restore)"}
              </ButtonItem>
            </PanelSectionRow>
            {(!autoLaunch || !g.appId) && lg.launchOptions && (
              <PanelSectionRow>
                <Field label="Launch options" description={lg.launchOptions} focusable={false} />
              </PanelSectionRow>
            )}
            <PanelSectionRow>
              <div style={{ fontSize: 11, opacity: 0.7 }}>
                Start the game, pick DLSS, XeSS or FSR in its graphics settings, play a few seconds, then press Check.
              </div>
            </PanelSectionRow>
          </>
        )}
      </>
    );
  };

  const ready = !!status?.weightsBuilt;
  const building = build?.state === "running";
  const lastLine = build?.log?.[build.log.length - 1];

  return (
    <>
      {error && (
        <PanelSection>
          <PanelSectionRow>
            <div style={{ color: "#ff6b6b", fontSize: 12, wordBreak: "break-word" }}>{error}</div>
          </PanelSectionRow>
        </PanelSection>
      )}

      <PanelSection title="Engine">
        <PanelSectionRow>
          <Field label={`HelixSR ${status?.version ?? ""}`} focusable={false}>
            {ready ? "Network ready" : status?.coreExists ? "Network not built" : "Core missing"}
          </Field>
        </PanelSectionRow>
        {!ready && (
          <PanelSectionRow>
            <ButtonItem layout="below" disabled={building || !status?.coreExists} onClick={doBuild}>
              {building ? "Building network..." : "Build network"}
            </ButtonItem>
          </PanelSectionRow>
        )}
        {building && lastLine && (
          <PanelSectionRow>
            <div style={{ fontSize: 11, opacity: 0.7, wordBreak: "break-all" }}>{lastLine}</div>
          </PanelSectionRow>
        )}
      </PanelSection>

      <PanelSection title="Game">
        <PanelSectionRow>
          <DropdownItem
            label={runningFolder && runningFolder === folder ? "Running now" : "Pick a game"}
            menuLabel="Games"
            strDefaultLabel={games.length ? "Choose a game" : "No supported games found"}
            disabled={!games.length || !!busy}
            rgOptions={games.map((g) => ({
              data: g.folder,
              label: `${g.installed || g.lite?.installed ? "● " : ""}${g.name}${g.native ? " (native Linux)" : ""}${g.folder === runningFolder ? " (running)" : ""}`,
            }))}
            selectedOption={folder}
            onChange={(o) => setFolder(o.data)}
          />
        </PanelSectionRow>

        {game && (
          <>
            <PanelSectionRow>
              <Field label="Status" focusable={false}>
                {game.native
                  ? "Native Linux game: not supported"
                  : game.lite?.installed
                    ? `FSR 4 Lite · ${game.lite.label ?? ""}`
                    : game.installed
                      ? `${game.routeDisplay} · ${game.version ?? ""}`
                      : "Not installed"}
              </Field>
            </PanelSectionRow>
            {!!game.inputs?.length && (
              <PanelSectionRow>
                <Field label="Game supports" focusable={false}>
                  {game.inputs.join(", ")}
                </Field>
              </PanelSectionRow>
            )}
          </>
        )}
      </PanelSection>

      {game?.native && (
        <PanelSection>
          <PanelSectionRow>
            <div style={{ fontSize: 11, opacity: 0.7 }}>
              {game.name} runs natively on Linux. HelixSR, OptiScaler and FSR 4 Lite hook Windows DirectX/Vulkan games
              running through Proton, so there is nothing to install for it.
            </div>
          </PanelSectionRow>
        </PanelSection>
      )}

      {game && !game.native && (
        <PanelSection title={game.installed || game.lite?.installed ? "Change" : "Install with"}>
          <PanelSectionRow>
            <DropdownItem
              label="Method"
              rgOptions={[
                ...(game.lite?.eligible || game.lite?.installed ? [LITE_METHOD] : []),
                ...ROUTES.filter((r) => r.id !== "dlss" || caps?.dlssLoader),
              ].map((r) => ({ data: r.id, label: r.label }))}
              selectedOption={route}
              onChange={(o) => setRoute(o.data)}
            />
          </PanelSectionRow>
          {!game.lite?.eligible && !game.lite?.installed && !!game.lite?.reasons?.length && (
            <PanelSectionRow>
              <div style={{ fontSize: 11, opacity: 0.7 }}>FSR 4 Lite: {game.lite.reasons.join("; ")}</div>
            </PanelSectionRow>
          )}

          {route === "fsr4lite" && renderLite(game)}
          {route !== "fsr4lite" && (
            <>

          {route === "optiscaler" && (
            <>
              <PanelSectionRow>
                <DropdownItem
                  label="OptiScaler proxy DLL"
                  rgOptions={(caps?.optiDlls ?? ["dxgi.dll"]).map((d) => ({ data: d, label: d }))}
                  selectedOption={optiDll}
                  onChange={(o) => setOptiDll(o.data)}
                />
              </PanelSectionRow>
              <PanelSectionRow>
                <DropdownItem
                  label="Frame generation"
                  rgOptions={(caps?.fgModes ?? [{ id: "auto", label: "Game default" }]).map((m) => ({ data: m.id, label: m.label }))}
                  selectedOption={fgMode}
                  onChange={(o) => setFgMode(o.data)}
                />
              </PanelSectionRow>
              <PanelSectionRow>
                <ToggleField
                  label="FakeNVAPI"
                  description="Unlocks DLSS options in games that hide them on AMD."
                  checked={fakeNvapi || fgMode.startsWith("dlssg_")}
                  disabled={fgMode.startsWith("dlssg_")}
                  onChange={setFakeNvapi}
                />
              </PanelSectionRow>
            </>
          )}

          {game.isReEngine && (
            <PanelSectionRow>
              <ToggleField label="REFramework Nightly" checked={reframework} onChange={setReframework} />
            </PanelSectionRow>
          )}

          <PanelSectionRow>
            <ButtonItem layout="below" disabled={!ready || !!busy || !!game.lite?.installed} onClick={doInstall}>
              {busy === "install" ? "Installing..." : game.installed ? "Reinstall HelixSR" : "Install HelixSR"}
            </ButtonItem>
          </PanelSectionRow>
          {game.lite?.installed && (
            <PanelSectionRow>
              <div style={{ fontSize: 11, opacity: 0.7 }}>FSR 4 Lite is enabled in this game; disable it first.</div>
            </PanelSectionRow>
          )}
          {game.installed && (
            <PanelSectionRow>
              <ButtonItem layout="below" disabled={!!busy} onClick={doUninstall}>
                {busy === "uninstall" ? "Removing..." : "Uninstall (restore original files)"}
              </ButtonItem>
            </PanelSectionRow>
          )}
          <PanelSectionRow>
            <ButtonItem layout="below" disabled={!!busy} onClick={doClearCache}>
              Clear shader cache
            </ButtonItem>
          </PanelSectionRow>
          {game.installed && game.protonLaunchOptions && (!autoLaunch || !game.appId) && (
            <PanelSectionRow>
              <Field label="Launch options" description={game.protonLaunchOptions} focusable={false} />
            </PanelSectionRow>
          )}
            </>
          )}
          {runningFolder === game.folder && (
            <PanelSectionRow>
              <div style={{ fontSize: 11, opacity: 0.7 }}>Restart the game for changes to take effect.</div>
            </PanelSectionRow>
          )}
        </PanelSection>
      )}

      <PanelSection title="Settings">
        <PanelSectionRow>
          <ToggleField
            label="Set Steam launch options"
            description="Adds or removes the WINEDLLOVERRIDES HelixSR needs when you install or uninstall."
            checked={autoLaunch}
            onChange={toggleAutoLaunch}
          />
        </PanelSectionRow>
        <PanelSectionRow>
          <ButtonItem
            layout="below"
            disabled={!!busy}
            onClick={() =>
              run("scan", async () => {
                const list = await loadGames(true);
                notify("HelixSR", `Found ${list.length} supported game(s)`);
              })
            }
          >
            {busy === "scan" ? "Scanning..." : "Rescan library"}
          </ButtonItem>
        </PanelSectionRow>
      </PanelSection>
    </>
  );
}

export default definePlugin(() => ({
  name: "HelixSR Manager",
  titleView: <div className={staticClasses.Title}>HelixSR</div>,
  content: <Content />,
  icon: <FaBolt />,
}));
