import assert from "node:assert/strict";
import { beforeEach, test } from "node:test";
import { clearPicks, currentMethod, defaultMethod, pick, picked } from "../src/method.ts";
import type { Method, MethodContext, MethodGame } from "../src/method.ts";

const AMD: MethodContext = { scalerReady: true, dlssLoader: false, preferLite: true };
const ALL: Method[] = ["fsr4lite", "scaler", "optiscaler", "direct"];
const fresh: MethodGame = { folder: "/games/oth", route: "optiscaler", installed: false, lite: { installed: false, eligible: true } };

beforeEach(() => clearPicks());

test("FSR 4 Lite is the initial default on AMD for eligible games", () => {
  assert.equal(defaultMethod(fresh, AMD), "fsr4lite");
  assert.equal(currentMethod(fresh, AMD, ALL), "fsr4lite");
});

test("a picked method sticks across remounts instead of snapping back to Lite", () => {
  pick(fresh.folder, "method", "scaler");
  // The panel remounts: a new render asks again with the same game and context.
  assert.equal(currentMethod(fresh, AMD, ALL), "scaler");
  assert.equal(currentMethod({ ...fresh }, { ...AMD }, [...ALL]), "scaler");
  pick(fresh.folder, "method", "optiscaler");
  assert.equal(currentMethod(fresh, AMD, ALL), "optiscaler");
  pick(fresh.folder, "method", "fsr4lite");
  assert.equal(currentMethod(fresh, AMD, ALL), "fsr4lite");
});

test("picks are per game", () => {
  pick(fresh.folder, "method", "direct");
  const other = { ...fresh, folder: "/games/other" };
  assert.equal(currentMethod(other, AMD, ALL), "fsr4lite");
  assert.equal(currentMethod(fresh, AMD, ALL), "direct");
});

test("a pick that is no longer offered falls back to the default", () => {
  pick(fresh.folder, "method", "hlxfsr");
  assert.equal(currentMethod(fresh, AMD, ALL), "fsr4lite");
});

test("other choices are remembered too", () => {
  pick(fresh.folder, "optiDll", "winmm.dll");
  pick(fresh.folder, "fgMode", "nofg");
  pick(fresh.folder, "fakeNvapi", false);
  assert.deepEqual(picked(fresh.folder), { optiDll: "winmm.dll", fgMode: "nofg", fakeNvapi: false });
  assert.deepEqual(picked("/games/none"), {});
});

test("defaults without a pick", () => {
  assert.equal(defaultMethod({ ...fresh, lite: { installed: true, eligible: true } }, AMD), "fsr4lite");
  assert.equal(defaultMethod({ ...fresh, installed: true, route: "direct" }, AMD), "direct");
  assert.equal(defaultMethod(fresh, { ...AMD, preferLite: false }), "scaler");
  assert.equal(defaultMethod(fresh, { scalerReady: false, dlssLoader: false, preferLite: false }), "optiscaler");
  assert.equal(defaultMethod({ ...fresh, installed: true, route: "dlss" }, AMD), "optiscaler");
  assert.equal(defaultMethod({ ...fresh, lite: { eligible: false } }, AMD), "scaler");
});
