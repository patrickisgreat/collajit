import { describe, expect, it } from "vitest";

import { asset } from "./api";
import { physicalGrid } from "./helpers";

describe("physicalGrid", () => {
  it("derives a 30x30 = 900 grid for 7.5in @ 0.25in tiles, 300 dpi", () => {
    const g = physicalGrid(7.5, 7.5, 30, 300);
    expect(g.cols).toBe(30);
    expect(g.rows).toBe(30);
    expect(g.tiles).toBe(900);
    expect(g.tilePx).toBe(75);
    expect(g.outW).toBe(2250);
    expect(g.outH).toBe(2250);
  });

  it("derives rows from a non-square canvas aspect", () => {
    const g = physicalGrid(10, 5, 20, 100); // 2:1 canvas
    expect(g.cols).toBe(20);
    expect(g.rows).toBe(10);
  });

  it("guards against zero/negative tiles", () => {
    expect(physicalGrid(7.5, 7.5, 0, 300).cols).toBe(1);
  });
});

describe("asset", () => {
  it("prefixes backend-relative paths and leaves absolute URLs untouched", () => {
    expect(asset("/outputs/x.png").endsWith("/outputs/x.png")).toBe(true);
    expect(asset("http://example/x.png")).toBe("http://example/x.png");
  });
});
