// Generates the backdrop art: 64×64 "HD texture pack" blocks and a pixel-art landscape
// per dimension. Deterministic (seeded), dependency-free, and checked in, so this only
// needs re-running after changing it: `npm run art`.
import { mkdirSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { deflateSync } from "node:zlib";

const PUBLIC = join(dirname(fileURLToPath(import.meta.url)), "..", "public");

// ---------------------------------------------------------------------------------
// Shared helpers

/** mulberry32: small, fast, and the same sequence on every machine. */
function rng(seed) {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

const hex = (color) => [1, 3, 5].map((i) => parseInt(color.slice(i, i + 2), 16));
const clamp = (value, low, high) => Math.min(high, Math.max(low, value));
const pick = (rand, items) => items[Math.floor(rand() * items.length)];

// ---------------------------------------------------------------------------------
// Textures

const SIZE = 64;

/** Smooth value noise on a lattice that wraps at the tile edge, so the tile repeats seamlessly. */
function noise(rand, cellsX, cellsY = cellsX) {
  const grid = Array.from({ length: cellsX * cellsY }, rand);
  const at = (i, j) => grid[(((j % cellsY) + cellsY) % cellsY) * cellsX + (((i % cellsX) + cellsX) % cellsX)];
  const ease = (t) => t * t * (3 - 2 * t);
  return (x, y) => {
    const fx = (x / SIZE) * cellsX;
    const fy = (y / SIZE) * cellsY;
    const i = Math.floor(fx);
    const j = Math.floor(fy);
    const tx = ease(fx - i);
    const ty = ease(fy - j);
    const top = at(i, j) + (at(i + 1, j) - at(i, j)) * tx;
    const bottom = at(i, j + 1) + (at(i + 1, j + 1) - at(i, j + 1)) * tx;
    return top + (bottom - top) * ty;
  };
}

/** A 64×64 field of palette indices, built from layered noise plus per-pixel grain. */
function field(rand, palette, layers, grain) {
  const raw = new Float64Array(SIZE * SIZE);
  for (let y = 0; y < SIZE; y++) {
    for (let x = 0; x < SIZE; x++) {
      let value = grain * rand();
      for (const [weight, sample] of layers) value += weight * sample(x, y);
      raw[y * SIZE + x] = value;
    }
  }
  // Stretch to the full palette so every shade gets used.
  let low = Infinity;
  let high = -Infinity;
  for (const value of raw) {
    low = Math.min(low, value);
    high = Math.max(high, value);
  }
  const shades = palette.length;
  return Array.from(raw, (value) =>
    clamp(Math.floor(((value - low) / (high - low)) * shades), 0, shades - 1),
  );
}

class Tile {
  constructor(palette, indices) {
    this.pixels = indices.map((index) => palette[index]);
  }
  set(x, y, color) {
    this.pixels[((y + SIZE) % SIZE) * SIZE + ((x + SIZE) % SIZE)] = color;
  }
  get(x, y) {
    return this.pixels[((y + SIZE) % SIZE) * SIZE + ((x + SIZE) % SIZE)];
  }
}

/** A stone or pit: a small blob with light on its top-left edge and shadow bottom-right. */
function blob(tile, x, y, width, height, body, light, shade) {
  for (let dy = 0; dy < height; dy++) {
    for (let dx = 0; dx < width; dx++) {
      // Knock the corners off anything bigger than 2×2 so it doesn't read as a square.
      const corner = (dx === 0 || dx === width - 1) && (dy === 0 || dy === height - 1);
      if (corner && width > 2 && height > 2) continue;
      tile.set(x + dx, y + dy, body);
    }
  }
  if (light) tile.set(x + (width > 2 ? 1 : 0), y, light);
  if (shade) {
    tile.set(x + width - 1, y + height - 1, shade);
    if (width > 2) tile.set(x + width - 2, y + height - 1, shade);
  }
}

/** A crack: a wandering dark line, with a lit pixel above each step for depth. */
function crack(rand, tile, x, y, length, dark, lit) {
  let dx = rand() < 0.5 ? 1 : -1;
  for (let step = 0; step < length; step++) {
    tile.set(x, y, dark);
    if (lit && tile.get(x, y - 1) !== dark) tile.set(x, y - 1, lit);
    if (rand() < 0.65) x += dx;
    else y += rand() < 0.5 ? 1 : -1;
    if (rand() < 0.12) dx = -dx;
  }
}

function dirt() {
  const rand = rng(11);
  const palette = ["#3b2a1d", "#4a3524", "#57402b", "#654a33", "#73553b", "#836345", "#93724f"];
  const tile = new Tile(
    palette,
    field(rand, palette, [[0.5, noise(rand, 8)], [0.3, noise(rand, 16)]], 0.55),
  );
  for (let i = 0; i < 26; i++) {
    const [w, h] = pick(rand, [[2, 2], [3, 2], [2, 1], [3, 3], [1, 1]]);
    blob(tile, Math.floor(rand() * SIZE), Math.floor(rand() * SIZE), w, h, "#8a7b6a", "#a99a86", "#5b4e41");
  }
  for (let i = 0; i < 18; i++) {
    const [w, h] = pick(rand, [[2, 2], [3, 2], [2, 3]]);
    blob(tile, Math.floor(rand() * SIZE), Math.floor(rand() * SIZE), w, h, "#2c1f15", null, null);
  }
  return tile;
}

function netherrack() {
  const rand = rng(23);
  const palette = ["#3a0e0e", "#4c1414", "#5e1919", "#6f1f1f", "#812828", "#933333", "#a6413f"];
  // Wider than tall: netherrack's blotches run sideways.
  const tile = new Tile(
    palette,
    field(rand, palette, [[0.55, noise(rand, 4, 16)], [0.3, noise(rand, 16, 32)]], 0.45),
  );
  for (let i = 0; i < 16; i++) {
    crack(rand, tile, Math.floor(rand() * SIZE), Math.floor(rand() * SIZE), 6 + Math.floor(rand() * 12), "#2a0909", "#b2504c");
  }
  return tile;
}

function endStone() {
  const rand = rng(37);
  const palette = ["#b5b079", "#c2bd85", "#cdc98f", "#d7d39a", "#e0dca4", "#e9e6b0", "#f1eebd"];
  const tile = new Tile(
    palette,
    field(rand, palette, [[0.45, noise(rand, 8)], [0.25, noise(rand, 32)]], 0.6),
  );
  // Pits: shadowed on the top-left lip, lit on the bottom-right one.
  for (let i = 0; i < 34; i++) {
    const [w, h] = pick(rand, [[1, 1], [2, 1], [2, 2], [3, 2], [1, 2]]);
    const x = Math.floor(rand() * SIZE);
    const y = Math.floor(rand() * SIZE);
    blob(tile, x, y, w, h, "#9c9764", null, null);
    tile.set(x, y, "#868152");
    tile.set(x + w, y + h, "#f6f3c9");
  }
  return tile;
}

// PNG: 8-bit RGB, no filtering, one IDAT. Enough for a 64×64 tile.
const CRC_TABLE = Array.from({ length: 256 }, (_, n) => {
  let c = n;
  for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
  return c >>> 0;
});

function crc32(buffer) {
  let c = 0xffffffff;
  for (const byte of buffer) c = CRC_TABLE[(c ^ byte) & 0xff] ^ (c >>> 8);
  return (c ^ 0xffffffff) >>> 0;
}

function chunk(type, data) {
  const length = Buffer.alloc(4);
  length.writeUInt32BE(data.length);
  const body = Buffer.concat([Buffer.from(type, "ascii"), data]);
  const crc = Buffer.alloc(4);
  crc.writeUInt32BE(crc32(body));
  return Buffer.concat([length, body, crc]);
}

function png(tile) {
  const raw = Buffer.alloc((SIZE * 3 + 1) * SIZE);
  for (let y = 0; y < SIZE; y++) {
    const row = y * (SIZE * 3 + 1);
    raw[row] = 0;
    for (let x = 0; x < SIZE; x++) {
      const [r, g, b] = hex(tile.pixels[y * SIZE + x]);
      raw.set([r, g, b], row + 1 + x * 3);
    }
  }
  const header = Buffer.alloc(13);
  header.writeUInt32BE(SIZE, 0);
  header.writeUInt32BE(SIZE, 4);
  header.set([8, 2, 0, 0, 0], 8);
  return Buffer.concat([
    Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]),
    chunk("IHDR", header),
    chunk("IDAT", deflateSync(raw, { level: 9 })),
    chunk("IEND", Buffer.alloc(0)),
  ]);
}

// ---------------------------------------------------------------------------------
// Scenes: 480×270 "pixels", drawn as crisp-edged SVG so they stay sharp at any size.

const W = 480;
const H = 270;

class Scene {
  constructor() {
    this.parts = [];
  }
  rect(x, y, width, height, fill, opacity) {
    if (width <= 0 || height <= 0) return;
    const alpha = opacity === undefined ? "" : ` fill-opacity="${opacity}"`;
    this.parts.push(`<rect x="${x}" y="${y}" width="${width}" height="${height}" fill="${fill}"${alpha}/>`);
  }
  path(d, fill, opacity) {
    const alpha = opacity === undefined ? "" : ` fill-opacity="${opacity}"`;
    this.parts.push(`<path d="${d}" fill="${fill}"${alpha}/>`);
  }
  /** Stepped sky bands, top to bottom. */
  bands(colors, top = 0, bottom = H) {
    const step = (bottom - top) / colors.length;
    colors.forEach((color, i) =>
      this.rect(0, Math.round(top + i * step), W, Math.ceil(step) + 1, color),
    );
  }
  svg() {
    return [
      `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${W} ${H}" width="${W * 4}" height="${H * 4}"`,
      ` preserveAspectRatio="xMidYMax slice" shape-rendering="crispEdges">`,
      ...this.parts,
      `</svg>\n`,
    ].join("");
  }
}

/** Block-quantised terrain heights: a smoothed random walk, snapped to the block grid. */
function heights(rand, block, low, high, roughness = 1) {
  const columns = Math.ceil(W / block);
  let level = low + rand() * (high - low);
  let drift = 0;
  return Array.from({ length: columns }, () => {
    drift = clamp(drift + (rand() - 0.5) * block * roughness, -block, block);
    level = clamp(level + drift, low, high);
    return Math.round(level / block) * block;
  });
}

/** A ground silhouette: each column filled from its height to the bottom. */
function ridge(scene, tops, block, fill, opacity) {
  let d = `M0 ${H}`;
  tops.forEach((top, i) => {
    d += `V${top}H${Math.min(W, (i + 1) * block)}`;
  });
  scene.path(`${d}V${H}Z`, fill, opacity);
}

/** The mirror of `ridge`: hangs from the top, for the Nether's ceiling. */
function ceiling(scene, bottoms, block, fill) {
  let d = "M0 0";
  bottoms.forEach((bottom, i) => {
    d += `V${bottom}H${Math.min(W, (i + 1) * block)}`;
  });
  scene.path(`${d}V0Z`, fill);
}

function overworld() {
  const rand = rng(101);
  const scene = new Scene();
  scene.bands([
    "#1b2346", "#24305a", "#33396b", "#4a4277", "#674a7d", "#8a527c",
    "#ad5d74", "#cc6e69", "#e3845f", "#f1a05b", "#f8be64",
  ], 0, 200);
  scene.rect(0, 200, W, 70, "#f8be64");

  // Sun, low on the horizon, with two square halos.
  scene.rect(318, 118, 60, 60, "#ffd88a", 0.18);
  scene.rect(328, 128, 40, 40, "#ffe19a", 0.35);
  scene.rect(336, 136, 24, 24, "#fff1c4");

  // Flat, blocky clouds catching the dusk light.
  for (let i = 0; i < 9; i++) {
    const x = Math.floor(rand() * W) - 20;
    const y = 18 + Math.floor(rand() * 90);
    const width = 24 + Math.floor(rand() * 7) * 8;
    const tone = y < 60 ? "#8e6c9c" : "#e79a8f";
    scene.rect(x, y, width, 4, tone, 0.55);
    scene.rect(x + 8, y - 4, width - 20, 4, tone, 0.45);
    scene.rect(x + 4, y + 4, width - 8, 2, "#000000", 0.08);
  }

  // Three ridges, nearer ones darker and in bigger blocks.
  ridge(scene, heights(rand, 4, 132, 182, 1.4), 4, "#5b4a7a", 0.85);
  const hills = heights(rand, 8, 168, 212, 1.2);
  ridge(scene, hills, 8, "#2f4637");
  // Trees on the middle ridge: a trunk and a two-tier canopy, in silhouette.
  hills.forEach((top, i) => {
    if (rand() > 0.22) return;
    const x = i * 8;
    scene.rect(x + 3, top - 10, 2, 10, "#1f2b22");
    scene.rect(x - 4, top - 22, 16, 12, "#243a2b");
    scene.rect(x, top - 26, 8, 4, "#243a2b");
  });

  // Foreground: grass-topped dirt in 16-pixel blocks, with a faint block grid.
  const ground = heights(rand, 8, 226, 246, 0.8);
  ground.forEach((top, i) => {
    const x = i * 8;
    scene.rect(x, top, 8, H - top, "#5e412b");
    for (let y = top + 8; y < H; y += 8) {
      scene.rect(x, y, 8, 8, rand() < 0.5 ? "#6a4a31" : "#563b27");
      if (rand() < 0.18) scene.rect(x + 2 + Math.floor(rand() * 3), y + 2 + Math.floor(rand() * 3), 2, 2, "#8a7b6a");
    }
    scene.rect(x, top, 8, 3, "#6bad3a");
    scene.rect(x, top + 3, 8, 2, "#4f8a2b");
    scene.rect(x + Math.floor(rand() * 6), top + 5, 2, 2, "#4f8a2b");
    // Tall grass and the odd flower.
    if (rand() < 0.35) scene.rect(x + 1 + Math.floor(rand() * 5), top - 3, 1, 3, "#7cc046");
    if (rand() < 0.08) {
      const fx = x + 2 + Math.floor(rand() * 4);
      scene.rect(fx, top - 4, 1, 4, "#3f7a26");
      scene.rect(fx - 1, top - 6, 3, 2, pick(rand, ["#e8463c", "#f4d23c", "#8f6be8"]));
    }
  });
  return scene.svg();
}

function nether() {
  const rand = rng(202);
  const scene = new Scene();
  scene.bands(["#170505", "#200707", "#2b0a09", "#390d0b", "#4a120d", "#5e190f", "#762311", "#8f2f12"], 0, 226);

  // Distant fortress bridge: a deck on pillars, in silhouette.
  ridge(scene, heights(rand, 4, 120, 170, 1.6), 4, "#521813", 0.75);
  scene.rect(0, 160, W, 8, "#2c0b0f");
  scene.rect(0, 156, W, 2, "#2c0b0f");
  for (let x = 6; x < W; x += 40) {
    scene.rect(x, 168, 12, 60, "#260a0d");
    scene.rect(x - 2, 168, 16, 4, "#260a0d");
  }
  for (let x = 0; x < W; x += 8) scene.rect(x, 154, 4, 2, "#2c0b0f");

  // Nearer cliffs in front of the bridge.
  ridge(scene, heights(rand, 8, 186, 214, 1.4), 8, "#3e100f");

  // Lava falls from the ceiling down to the sea.
  for (const x of [58, 214, 402]) {
    scene.rect(x, 0, 8, 226, "#e2621a");
    scene.rect(x + 2, 0, 3, 226, "#ffad3a");
    scene.rect(x - 2, 216, 12, 10, "#ff8a26", 0.6);
  }

  // Ceiling of hanging netherrack, with glowstone clusters tucked under it.
  const roof = heights(rand, 8, 18, 78, 1.8);
  ceiling(scene, roof, 8, "#100303");
  roof.forEach((bottom, i) => {
    const x = i * 8;
    // A lit underside where the lava glow catches the rock.
    scene.rect(x, bottom - 2, 8, 2, "#4a1311");
    if (rand() > 0.14) return;
    scene.rect(x, bottom, 8, 6, "#c08a2e");
    scene.rect(x + 1, bottom, 6, 4, "#f2c94c");
    scene.rect(x + 2, bottom + 1, 2, 2, "#fff0b0");
    scene.rect(x + 2, bottom + 6, 4, 3, "#e0ad3c");
  });

  // Lava sea: bright surface line, banded body, bubbles.
  scene.rect(0, 226, W, H - 226, "#d2561a");
  scene.rect(0, 226, W, 3, "#ffc04a");
  scene.rect(0, 229, W, 4, "#f0761f");
  for (let i = 0; i < 70; i++) {
    const x = Math.floor(rand() * W);
    const y = 234 + Math.floor(rand() * 36);
    scene.rect(x, y, 2 + Math.floor(rand() * 6), 2, rand() < 0.5 ? "#f08a2a" : "#b8461a");
  }
  for (let i = 0; i < 14; i++) scene.rect(Math.floor(rand() * W), 230 + Math.floor(rand() * 30), 2, 2, "#ffe08a");

  // Netherrack shores either side.
  const shore = (from, to, low, high) => {
    for (let x = from; x < to; x += 8) {
      const top = Math.round((low + rand() * (high - low)) / 8) * 8;
      for (let y = top; y < H; y += 8) scene.rect(x, y, 8, 8, rand() < 0.5 ? "#6b1e1c" : "#5a1818");
      scene.rect(x, top, 8, 2, "#8a2c28");
      if (rand() < 0.5) scene.rect(x + 2, top + 4 + Math.floor(rand() * 10), 3, 1, "#2a0909");
    }
  };
  shore(0, 96, 214, 242);
  shore(400, W, 208, 240);
  return scene.svg();
}

function end() {
  const rand = rng(303);
  const scene = new Scene();
  scene.bands(["#06040b", "#090610", "#0d0916", "#120c1d", "#171024", "#1d142c", "#231834"]);

  for (let i = 0; i < 140; i++) {
    const size = rand() < 0.85 ? 1 : 2;
    scene.rect(Math.floor(rand() * W), Math.floor(rand() * 220), size, size, "#efe8ff", (0.25 + rand() * 0.7).toFixed(2));
  }
  // A faint purple haze around the island.
  scene.rect(0, 150, W, 90, "#6a3e9e", 0.08);
  scene.rect(0, 175, W, 50, "#6a3e9e", 0.08);

  /** A floating island: a stepped top and an underside tapering to a point. */
  const island = (centre, top, width, depth, block, colors) => {
    const columns = Math.floor(width / block);
    const left = centre - Math.floor(columns / 2) * block;
    for (let c = 0; c < columns; c++) {
      const x = left + c * block;
      const edge = Math.min(c, columns - 1 - c);
      const surface = top - (edge > 2 ? Math.round(rand() * 1) * block : 0);
      const bottom = top + Math.round((depth * Math.sin(((c + 0.5) / columns) * Math.PI)) / block) * block;
      scene.rect(x, surface, block, Math.max(block, bottom - surface), colors.body);
      scene.rect(x, surface, block, Math.max(1, block / 4), colors.top);
      for (let y = surface + block; y < bottom; y += block) {
        if (rand() < 0.3) scene.rect(x, y, block, block, colors.shade);
      }
      scene.rect(x, bottom - block, block, block, colors.under);
    }
  };

  island(70, 120, 48, 28, 4, { top: "#8e8a62", body: "#77734f", shade: "#6a6646", under: "#55523a" });
  island(424, 96, 36, 20, 4, { top: "#8e8a62", body: "#77734f", shade: "#6a6646", under: "#55523a" });

  // Obsidian pillars, some still crowned with a crystal, standing on the main island.
  const pillars = [
    [184, 14, 92, true],
    [222, 12, 60, false],
    [300, 16, 120, true],
    [348, 12, 74, false],
  ];
  for (const [x, width, height, crystal] of pillars) {
    const base = 206;
    scene.rect(x, base - height, width, height, "#170e22");
    scene.rect(x, base - height, 2, height, "#2b1c40");
    scene.rect(x + width - 2, base - height, 2, height, "#0e0816");
    scene.rect(x, base - height, width, 2, "#3a2756");
    if (crystal) {
      const cx = x + width / 2 - 4;
      const cy = base - height - 14;
      scene.rect(cx - 10, cy - 10, 28, 28, "#e07ef0", 0.12);
      scene.rect(cx - 2, cy - 2, 12, 12, "#c85ee0", 0.5);
      scene.rect(cx, cy, 8, 8, "#f4b6ff");
      scene.rect(cx + 2, cy + 2, 4, 4, "#ffffff");
      scene.rect(cx + 3, cy + 8, 2, 6, "#f4b6ff", 0.4);
    }
  }

  island(270, 204, 288, 70, 8, { top: "#e6e2a9", body: "#cdc88d", shade: "#bdb87e", under: "#9a9563" });
  return scene.svg();
}

// ---------------------------------------------------------------------------------

function write(relative, contents) {
  const file = join(PUBLIC, relative);
  mkdirSync(dirname(file), { recursive: true });
  writeFileSync(file, contents);
  console.log(`wrote public/${relative}`);
}

write("textures/hd/dirt.png", png(dirt()));
write("textures/hd/netherrack.png", png(netherrack()));
write("textures/hd/end_stone.png", png(endStone()));
write("scenes/overworld.svg", overworld());
write("scenes/nether.svg", nether());
write("scenes/end.svg", end());
