import assert from "node:assert/strict";
import { test } from "node:test";
import { addTracked, applyOverrides, overridesFrom, restoreTracked } from "../src/launchOptions.ts";

test("parses the engine's launch option", () => {
  assert.deepEqual(overridesFrom('WINEDLLOVERRIDES="dxgi,dinput8=n,b" %command%'), ["dxgi", "dinput8"]);
  assert.deepEqual(overridesFrom(""), []);
});

test("empty options get the full launch option", () => {
  assert.equal(applyOverrides("", ["dxgi"], []), 'WINEDLLOVERRIDES="dxgi=n,b" %command%');
});

test("keeps other env vars and arguments", () => {
  assert.equal(
    applyOverrides("PROTON_LOG=1 %command% -dx12", ["winmm"], []),
    'WINEDLLOVERRIDES="winmm=n,b" PROTON_LOG=1 %command% -dx12',
  );
});

test("arguments without %command% stay arguments", () => {
  assert.equal(applyOverrides("-skipintro", ["dxgi"], []), 'WINEDLLOVERRIDES="dxgi=n,b" %command% -skipintro');
});

test("merges with the user's own overrides", () => {
  assert.equal(
    applyOverrides('WINEDLLOVERRIDES="xinput1_3=n" %command%', ["dxgi"], []),
    'WINEDLLOVERRIDES="xinput1_3=n;dxgi=n,b" %command%',
  );
});

test("switching proxy DLL replaces the old one", () => {
  assert.equal(
    applyOverrides('WINEDLLOVERRIDES="dxgi=n,b" %command%', ["winmm"], ["dxgi"]),
    'WINEDLLOVERRIDES="winmm=n,b" %command%',
  );
});

test("removing the last override cleans up", () => {
  assert.equal(applyOverrides('WINEDLLOVERRIDES="dxgi=n,b" %command%', [], ["dxgi"]), "");
  assert.equal(applyOverrides('WINEDLLOVERRIDES=dxgi=n,b MANGOHUD=1 %command%', [], ["dxgi"]), "MANGOHUD=1 %command%");
});

test("idempotent", () => {
  const once = applyOverrides("", ["dxgi", "dinput8"], []);
  assert.equal(applyOverrides(once, ["dxgi", "dinput8"], []), once);
});

test("FSR 4 Lite: uninstall restores the exact original options", () => {
  const original = "PROTON_LOG=1   %command% -dx12";
  const rec = addTracked(original, ["dxgi"]);
  assert.equal(rec.applied, 'WINEDLLOVERRIDES="dxgi=n,b" PROTON_LOG=1 %command% -dx12');
  assert.deepEqual(rec.added, ["dxgi"]);
  assert.equal(restoreTracked(rec.applied, rec), original);
});

test("FSR 4 Lite: an override the user already had is kept on uninstall", () => {
  const original = 'WINEDLLOVERRIDES="dxgi=n,b" %command%';
  const rec = addTracked(original, ["dxgi"]);
  assert.deepEqual(rec.added, []);
  // User edited the options afterwards: nothing of theirs is removed.
  assert.equal(restoreTracked('WINEDLLOVERRIDES="dxgi=n,b" %command% -windowed', rec), 'WINEDLLOVERRIDES="dxgi=n,b" %command% -windowed');
});

test("FSR 4 Lite: user edits after install survive, only our override goes", () => {
  const rec = addTracked("", ["winmm"]);
  const edited = rec.applied + " -nosplash";
  assert.equal(restoreTracked(edited, rec), "%command% -nosplash");
});

test("FSR 4 Lite: re-applying keeps the first original", () => {
  const first = addTracked("-high", ["dxgi"]);
  const again = addTracked(first.applied, ["dxgi"], first);
  assert.equal(again.original, "-high");
  assert.equal(restoreTracked(again.applied, again), "-high");
});
