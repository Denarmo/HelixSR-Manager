// Which install method the panel shows for a game.
//
// Steam remounts the Quick Access panel when a dropdown closes, so React state does not survive a pick.
// The user's choice is kept per game folder at module level (for as long as the plugin is loaded) and always
// wins over the defaults. FSR 4 Lite is only the initial default.

export type Route = "optiscaler" | "direct" | "dlss" | "scaler" | "hlxfsr";
export type Method = Route | "fsr4lite";

export interface MethodGame {
  folder: string;
  route: Route;
  installed: boolean;
  lite?: { installed?: boolean; eligible?: boolean } | null;
}

export interface MethodContext {
  /** HelixSR 3.2.0 Scaler is built and available. */
  scalerReady: boolean;
  /** The DLSS Loader route is available in this build. */
  dlssLoader: boolean;
  /** AMD GPU: prefer FSR 4 Lite for eligible games. */
  preferLite: boolean;
}

/** The method a game starts on before the user picks one. */
export function defaultMethod(game: MethodGame, ctx: MethodContext): Method {
  if (game.lite?.installed) return "fsr4lite";
  // FSR 4 Lite is the default on AMD handhelds for games it can go in, unless HelixSR is already installed there.
  if (ctx.preferLite && game.lite?.eligible && !game.installed) return "fsr4lite";
  if (!game.installed && ctx.scalerReady) return "scaler";
  if (game.route === "dlss" && !ctx.dlssLoader) return "optiscaler";
  return game.route;
}

/** Per-game choices the user made in the panel (method, proxy DLL, frame generation...). */
export interface Choices {
  method?: Method;
  liteProxy?: string;
  optiDll?: string;
  fgMode?: string;
  fakeNvapi?: boolean;
  reframework?: boolean;
}

const picks = new Map<string, Choices>();

/** Remember a choice for this game, so it survives the panel remounting. */
export function pick<K extends keyof Choices>(folder: string, key: K, value: Choices[K]): void {
  picks.set(folder, { ...picks.get(folder), [key]: value });
}

export function picked(folder: string): Choices {
  return picks.get(folder) ?? {};
}

/** The user's pick if it is still offered for this game, otherwise the default. */
export function currentMethod(game: MethodGame, ctx: MethodContext, offered: Method[]): Method {
  const p = picks.get(game.folder)?.method;
  if (p && offered.includes(p)) return p;
  return defaultMethod(game, ctx);
}

/** For tests. */
export function clearPicks(): void {
  picks.clear();
}
