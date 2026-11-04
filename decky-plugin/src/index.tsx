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
import { applyOverrides, overridesFrom } from "./launchOptions";

// ---------------------------------------------------------------------------
// Backend (main.py)
// ---------------------------------------------------------------------------

type Route = "optiscaler" | "direct" | "dlss" | "scaler" | "hlxfsr";

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
  helixsr3?: boolean;
  scalerVersion?: string | null;
  hasFsr31?: boolean;
}

interface HelixSR3Status {
  version: string;
  downloaded: boolean;
  networkReady: boolean;
  hlxReady: boolean;
  scalerReady: boolean;
  dropinReady: boolean;
  downloadSize: number;
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
  helixsr3?: HelixSR3Status;
  capabilities: {
    helixsr3?: { version: string; routes: Route[]; scalerDlls: string[]; downloadSize: number } | null;
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
const startBuild = callable<[core: string], Result>("start_build");
const buildStatus = callable<[], BuildState>("build_status");

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

// ---------------------------------------------------------------------------
// UI
// ---------------------------------------------------------------------------

const ROUTES: { id: Route; label: string }[] = [
  { id: "scaler", label: "HelixSR Scaler (HLX DLSS, recommended)" },
  { id: "hlxfsr", label: "HLX FSR 4 drop-in (FSR 3.1 games)" },
  { id: "optiscaler", label: "1.8.1: OptiScaler (DLSS / XeSS / FSR games)" },
  { id: "direct", label: "1.8.1: Direct FSR 3.1 replacement" },
  { id: "dlss", label: "1.8.1: DLSS Loader (experimental)" },
];

function notify(title: string, body: string) {
  toaster.toast({ title, body });
}

function Content() {
  const [status, setStatus] = useState<Status | null>(null);
  const [games, setGames] = useState<Game[]>([]);
  const [settings, setLocalSettings] = useState<Settings>({});
  const [folder, setFolder] = useState<string | null>(null);
  const [runningFolder, setRunningFolder] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [build, setBuild] = useState<BuildState | null>(null);

  // Per-install choices, reset whenever another game is picked.
  const [route, setRoute] = useState<Route>("optiscaler");
  const [optiDll, setOptiDll] = useState("dxgi.dll");
  const [fgMode, setFgMode] = useState("auto");
  const [fakeNvapi, setFakeNvapi] = useState(true);
  const [reframework, setReframework] = useState(false);
  const [fsr4Variant, setFsr4Variant] = useState<string | null>(null);

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
        if (st.building) setBuild({ state: "running", log: [] });
        const list = await loadGames(false);
        const app = Router.MainRunningApp;
        if (app?.appid) {
          const res = await findApp(String(app.appid));
          if (res.game) {
            upsertGame(res.game);
            setRunningFolder(res.game.folder);
            setFolder(res.game.folder);
            return;
          }
        }
        if (!list.length) await loadGames(true);
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
    const h3Ready = !!caps?.helixsr3 && !!status?.helixsr3?.scalerReady;
    if (!game.installed && h3Ready) setRoute("scaler");
    else setRoute(game.route === "dlss" && !caps?.dlssLoader ? "optiscaler" : game.route);
    setOptiDll(game.optiDllName || "dxgi.dll");
    setFgMode(game.fgMode || "auto");
    setFakeNvapi(game.useFakeNvapi !== false);
    setReframework(!!(game.installReFramework || game.isReEngine));
    const variants = caps?.fsr4Variants ?? [];
    const lite = variants.find((v) => v.id === "lite");
    setFsr4Variant(game.fsr4Variant || lite?.id || variants[0]?.id || null);
  }, [game?.folder, game?.installed, caps]);

  // Poll the network build while it runs.
  useEffect(() => {
    if (build?.state !== "running") return;
    const t = setInterval(async () => {
      const st = await buildStatus();
      if (!mounted.current) return;
      setBuild(st);
      if (st.state !== "running") {
        setStatus(await getStatus());
        notify("HelixSR", st.state === "done" ? "HelixSR is built. You can install it now." : st.error || "Build failed");
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
      if (route === "scaler") opts.optiDll = scalerDlls.includes(optiDll) ? optiDll : "dxgi.dll";
      if (route === "optiscaler") {
        opts.optiDll = optiDll;
        opts.fgMode = fgMode;
        opts.useFakeNvapi = fakeNvapi || fgMode.startsWith("dlssg_");
        if (fsr4Variant && caps?.fsr4Variants.length) opts.fsr4Variant = fsr4Variant;
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

  const doBuild = (core: "legacy" | "helixsr3" = "legacy") =>
    showModal(
      <ConfirmModal
        strTitle={core === "helixsr3" ? `Download and build HelixSR ${h3?.version ?? ""}` : "Build the HelixSR network"}
        strDescription={
          core === "helixsr3"
            ? (h3?.downloaded
                ? ""
                : `Downloads the official HelixSR ${h3?.version ?? ""} release from lonewolf0622/HelixSR ` +
                  `(${Math.round((caps?.helixsr3?.downloadSize ?? 0) / 1048576)} MB). `) +
              "HelixSR's own setup then downloads NVIDIA's DLSS 310.7.0 DLL from NVIDIA's GitHub (you accept NVIDIA's " +
              "license) and AMD's FSR 4 driver package (about 420 MB), and builds HLX DLSS and HLX FSR 4 on this device. " +
              "This takes several minutes; keep the device plugged in."
            : "HelixSR builds its network on this device from NVIDIA's DLSS 310.7.0 DLL (taken from one of your games, " +
              "or downloaded from NVIDIA's GitHub, which means you accept NVIDIA's license). " +
              "It also downloads Python and Microsoft's shader compiler once. This takes several minutes; keep the device plugged in."
        }
        strOKButtonText="Build"
        onOK={async () => {
          const res = await startBuild(core);
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

  const ready = !!status?.weightsBuilt;
  const h3 = caps?.helixsr3 ? status?.helixsr3 : undefined;
  const scalerDlls = caps?.helixsr3?.scalerDlls ?? ["dxgi.dll"];
  const routeReady = route === "scaler" ? !!h3?.scalerReady : route === "hlxfsr" ? !!h3?.dropinReady : ready;
  const routeOptions = ROUTES.filter((r) => {
    if (r.id === "dlss") return !!caps?.dlssLoader;
    if (r.id === "scaler") return !!h3;
    if (r.id === "hlxfsr") return !!h3 && !!game && (!!game.hasFsr31 || game.route === "hlxfsr");
    return true;
  });
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
        {h3 && (
          <>
            <PanelSectionRow>
              <Field label={`HelixSR ${h3.version}`} focusable={false}>
                {h3.scalerReady
                  ? h3.dropinReady
                    ? "Ready (HLX DLSS, HLX FSR 4)"
                    : "Ready (HLX DLSS)"
                  : h3.downloaded
                    ? "Not built"
                    : "Not downloaded"}
              </Field>
            </PanelSectionRow>
            {!h3.scalerReady && (
              <PanelSectionRow>
                <ButtonItem layout="below" disabled={building} onClick={() => doBuild("helixsr3")}>
                  {building ? "Building..." : h3.downloaded ? `Build HelixSR ${h3.version}` : `Download and build HelixSR ${h3.version}`}
                </ButtonItem>
              </PanelSectionRow>
            )}
          </>
        )}
        <PanelSectionRow>
          <Field label={`HelixSR ${status?.version ?? ""}${h3 ? " (1.8.1 methods)" : ""}`} focusable={false}>
            {ready ? "Network ready" : status?.coreExists ? "Network not built" : "Core missing"}
          </Field>
        </PanelSectionRow>
        {!ready && (
          <PanelSectionRow>
            <ButtonItem layout="below" disabled={building || !status?.coreExists} onClick={() => doBuild("legacy")}>
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
              label: `${g.installed ? "● " : ""}${g.name}${g.folder === runningFolder ? " (running)" : ""}`,
            }))}
            selectedOption={folder}
            onChange={(o) => setFolder(o.data)}
          />
        </PanelSectionRow>

        {game && (
          <>
            <PanelSectionRow>
              <Field label="Status" focusable={false}>
                {game.installed ? `${game.routeDisplay} · ${game.version ?? ""}` : "Not installed"}
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

      {game && (
        <PanelSection title={game.installed ? "Reinstall with" : "Install with"}>
          <PanelSectionRow>
            <DropdownItem
              label="Method"
              rgOptions={routeOptions.map((r) => ({ data: r.id, label: r.label }))}
              selectedOption={route}
              onChange={(o) => setRoute(o.data)}
            />
          </PanelSectionRow>

          {route === "scaler" && (
            <PanelSectionRow>
              <DropdownItem
                label="HelixSR Scaler file name"
                description="dxgi.dll needs no launch option. Press Insert in game for HelixSR Scaler's menu."
                rgOptions={scalerDlls.map((d) => ({ data: d, label: d }))}
                selectedOption={scalerDlls.includes(optiDll) ? optiDll : "dxgi.dll"}
                onChange={(o) => setOptiDll(o.data)}
              />
            </PanelSectionRow>
          )}

          {route === "optiscaler" && (
            <>
              {!!caps?.fsr4Variants.length && (
                <PanelSectionRow>
                  <DropdownItem
                    label="FSR 4 model"
                    description="Lite uses the lighter INT8 model, made for handheld APUs."
                    rgOptions={caps.fsr4Variants.map((v) => ({ data: v.id, label: v.label }))}
                    selectedOption={fsr4Variant}
                    onChange={(o) => setFsr4Variant(o.data)}
                  />
                </PanelSectionRow>
              )}
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
            <ButtonItem layout="below" disabled={!routeReady || !!busy} onClick={doInstall}>
              {busy === "install" ? "Installing..." : game.installed ? "Reinstall HelixSR" : "Install HelixSR"}
            </ButtonItem>
          </PanelSectionRow>
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
