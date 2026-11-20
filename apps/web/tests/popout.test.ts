import { test } from "node:test";
import assert from "node:assert/strict";
import {
  getPipApi,
  isPopoutSupported,
  openPopout,
  POPOUT_SIZE,
} from "../src/components/popout-window.ts";

test("feature detection", () => {
  assert.equal(isPopoutSupported({}), false);
  assert.equal(isPopoutSupported(undefined), false);
  assert.equal(isPopoutSupported({ documentPictureInPicture: {} }), false);
  const api = { requestWindow: async () => ({}) };
  assert.equal(getPipApi({ documentPictureInPicture: api }), api);
});

test("openPopout requests a 380x560 window and returns it", async () => {
  const fake = { closed: false };
  let opts: unknown;
  const win = {
    documentPictureInPicture: {
      requestWindow: async (o: unknown) => ((opts = o), fake),
    },
  };
  assert.equal(await openPopout(win), fake);
  assert.deepEqual(opts, { width: 380, height: 560 });
  assert.deepEqual(POPOUT_SIZE, { width: 380, height: 560 });
});

test("openPopout returns null when unsupported", async () => {
  assert.equal(await openPopout({}), null);
});
