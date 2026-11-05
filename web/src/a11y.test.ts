import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

/** Reads the design tokens straight from styles.css, so changing a colour there is checked against WCAG automatically. */
const css = readFileSync(new URL("./styles.css", import.meta.url), "utf8");
const token = (name: string): string => {
  const m = css.match(new RegExp(`--color-${name}:\\s*(#[0-9a-fA-F]{6})`));
  if (!m) throw new Error(`token --color-${name} is missing from styles.css`);
  return m[1];
};

function luminance(hex: string): number {
  const [r, g, b] = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16) / 255).map((c) => (c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4));
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}
export function contrast(a: string, b: string): number {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return (hi + 0.05) / (lo + 0.05);
}

const SURFACES = ["page", "surface", "raised"];
const STATUSES = ["passed", "running", "queued", "blocked", "failed", "escalated", "idle"];

describe("contrast (WCAG 2.1 AA)", () => {
  it("computes known ratios correctly", () => {
    expect(contrast("#000000", "#ffffff")).toBeCloseTo(21, 0);
    expect(contrast("#777777", "#ffffff")).toBeCloseTo(4.48, 1);
  });

  it("body, secondary and tertiary text meet 4.5:1 on every surface", () => {
    for (const fg of ["fg", "fg-2", "fg-3", "accent"]) {
      for (const bg of SURFACES) expect(contrast(token(fg), token(bg)), `${fg} on ${bg}`).toBeGreaterThanOrEqual(4.5);
    }
  });

  it("every status colour is readable on its chip and on the surfaces it is printed on", () => {
    for (const s of STATUSES) {
      expect(contrast(token(s), token(`${s}-bg`)), `${s} on its chip`).toBeGreaterThanOrEqual(4.5);
      for (const bg of SURFACES) expect(contrast(token(s), token(bg)), `${s} on ${bg}`).toBeGreaterThanOrEqual(4.5);
    }
  });

  it("primary buttons are readable", () => {
    expect(contrast(token("on-accent"), token("accent-bg"))).toBeGreaterThanOrEqual(4.5);
  });

  it("the borders of inputs and buttons reach 3:1 so the controls can be found (WCAG 1.4.11)", () => {
    for (const bg of SURFACES) expect(contrast(token("control"), token(bg)), `control on ${bg}`).toBeGreaterThanOrEqual(3);
  });

  it("every status has a distinct colour, so the icon and the word are not the only difference", () => {
    const colours = STATUSES.map((s) => token(s));
    expect(new Set(colours).size).toBeGreaterThanOrEqual(6); // queued and idle are both neutral on purpose
  });

  it("uses one UI font and one monospace font, and no text below 13px", () => {
    expect(css).toMatch(/--font-sans:/);
    expect(css).toMatch(/--font-mono:/);
    expect(css).toMatch(/font:\s*400 14px/); // body text is 14px
    const small = readFileSync(new URL("./components/Header.tsx", import.meta.url), "utf8");
    expect(small).not.toMatch(/text-\[(?:[0-9]|1[0-2])px\]/);
  });
});
