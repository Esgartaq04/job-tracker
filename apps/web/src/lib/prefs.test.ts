import { beforeEach, describe, expect, it } from "vitest";

import indexHtml from "../../index.html?raw";
import {
  applyPrefs,
  BACKDROPS,
  DIMENSIONS,
  PREFS_KEY,
  usePrefs,
  type Backdrop,
  type Dimension,
} from "./prefs";

// The script in index.html that applies saved prefs before first paint.
const bootScript = /<script>([\s\S]*?)<\/script>/.exec(indexHtml)![1];

/** Put <html> and the theme-color meta back the way index.html ships them. */
function resetDocument() {
  const root = document.documentElement;
  root.dataset.dimension = "overworld";
  root.dataset.font = "pixel";
  root.dataset.backdrop = "blocks";
  document.head.innerHTML = '<meta name="theme-color" content="#1c1611" />';
}

function snapshot() {
  const { dimension, font, backdrop } = document.documentElement.dataset;
  const theme = document.querySelector('meta[name="theme-color"]')?.getAttribute("content");
  return { dimension, font, backdrop, theme };
}

beforeEach(() => {
  localStorage.clear();
  resetDocument();
  usePrefs.setState({ backdrop: "blocks" });
});

describe("backdrop", () => {
  it("toggles between blocks and scenery, and persists the choice", () => {
    usePrefs.getState().toggleBackdrop();
    expect(usePrefs.getState().backdrop).toBe("scenery");
    expect(JSON.parse(localStorage.getItem(PREFS_KEY)!).state.backdrop).toBe("scenery");

    usePrefs.getState().toggleBackdrop();
    expect(usePrefs.getState().backdrop).toBe("blocks");
  });

  it("is mirrored onto <html> by applyPrefs", () => {
    applyPrefs("nether", true, "scenery");
    expect(document.documentElement.dataset.backdrop).toBe("scenery");
    applyPrefs("nether", true, "blocks");
    expect(document.documentElement.dataset.backdrop).toBe("blocks");
  });
});

describe("index.html boot script", () => {
  const cases: [Dimension, boolean, Backdrop][] = DIMENSIONS.flatMap((dimension) =>
    [true, false].flatMap((pixelFont) =>
      BACKDROPS.map((backdrop): [Dimension, boolean, Backdrop] => [dimension, pixelFont, backdrop]),
    ),
  );

  it.each(cases)("matches applyPrefs for %s, pixel font %s, %s", (dimension, pixelFont, backdrop) => {
    const saved = { state: { dimension, pixelFont, backdrop }, version: 0 };
    localStorage.setItem(PREFS_KEY, JSON.stringify(saved));
    new Function(bootScript)();
    const booted = snapshot();

    resetDocument();
    applyPrefs(dimension, pixelFont, backdrop);
    expect(booted).toEqual(snapshot());
  });
});
