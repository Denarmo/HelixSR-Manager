// Merges HelixSR's WINEDLLOVERRIDES into a game's existing Steam launch options
// without touching anything else the user put there.

const TOKEN_RE = /(^|\s)WINEDLLOVERRIDES=("([^"]*)"|'([^']*)'|(\S*))/;

/** DLL names a HelixSR launch option overrides, e.g. `WINEDLLOVERRIDES="dxgi,dinput8=n,b" %command%` -> ["dxgi", "dinput8"]. */
export function overridesFrom(option: string | null | undefined): string[] {
  return [...parse(option || "").keys()];
}

function parse(options: string): Map<string, string> {
  const map = new Map<string, string>();
  const m = TOKEN_RE.exec(options);
  if (!m) return map;
  const value = m[3] ?? m[4] ?? m[5] ?? "";
  for (const part of value.split(";")) {
    const eq = part.indexOf("=");
    if (eq < 0) continue;
    const mode = part.slice(eq + 1).trim();
    for (const dll of part.slice(0, eq).split(",")) {
      const d = dll.trim().toLowerCase();
      if (d) map.set(d, mode);
    }
  }
  return map;
}

/**
 * Returns `existing` with `add` set to native-then-builtin (n,b) and `remove` taken out
 * of WINEDLLOVERRIDES. Other overrides, env vars and arguments are kept.
 */
export function applyOverrides(existing: string | null | undefined, add: string[], remove: string[]): string {
  const opts = (existing || "").trim();
  const map = parse(opts);
  for (const d of remove) map.delete(d.toLowerCase());
  for (const d of add) map.set(d.toLowerCase(), "n,b");

  let rest = opts.replace(TOKEN_RE, "$1").replace(/\s+/g, " ").trim();
  if (map.size === 0) return rest === "%command%" ? "" : rest;

  const byMode = new Map<string, string[]>();
  for (const [dll, mode] of map) {
    byMode.set(mode, [...(byMode.get(mode) || []), dll]);
  }
  const value = [...byMode].map(([mode, dlls]) => `${dlls.join(",")}=${mode}`).join(";");
  const token = `WINEDLLOVERRIDES="${value}"`;
  if (rest.includes("%command%")) return `${token} ${rest}`;
  return rest ? `${token} %command% ${rest}` : `${token} %command%`;
}
