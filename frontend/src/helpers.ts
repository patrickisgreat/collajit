// Pure helpers, unit-tested in helpers.test.ts.

export interface Grid {
  cols: number;
  rows: number;
  tileIn: number;
  tilePx: number;
  tiles: number;
  outW: number;
  outH: number;
}

/**
 * Derive a mosaic grid from a physical canvas. Tiles-across is the control; tile
 * size is derived (mirrors the backend's PhysicalSpec). e.g. 7.5x7.5in @ 30 cols,
 * 300 dpi → 30x30 = 900 tiles, 0.25in / 75px each, 2250x2250px output.
 */
export function physicalGrid(
  canvasWIn: number,
  canvasHIn: number,
  cols: number,
  dpi: number
): Grid {
  const c = Math.max(1, Math.round(cols));
  const w = canvasWIn > 0 ? canvasWIn : 1;
  const tileIn = w / c;
  const rows = Math.max(1, Math.round((canvasHIn / w) * c));
  const tilePx = Math.max(1, Math.round(tileIn * dpi));
  return { cols: c, rows, tileIn, tilePx, tiles: c * rows, outW: c * tilePx, outH: rows * tilePx };
}
