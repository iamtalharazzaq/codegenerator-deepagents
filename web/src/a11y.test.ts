import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

/** Reads the design tokens straight from styles.css for BOTH themes, so changing a colour there is checked against WCAG
 * automatically. A colour change that breaks contrast in the dark or the light theme fails the build. */
const css = readFileSync(new URL("./styles.css", import.meta.url), "utf8");

const block = (selector: string): string => {
  const start = css.indexOf(`${selector} {`);
  if (start < 0) throw new Error(`${selector} block is missing from styles.css`);
  return css.slice(start, css.indexOf("\n}", start));
};
const THEMES = { dark: block(":root"), light: block(':root[data-theme="light"]') };
type Theme = keyof typeof THEMES;
const token = (theme: Theme, name: string): string => {
  const m = THEMES[theme].match(new RegExp(`--${name}:\\s*(#[0-9a-fA-F]{6})`));
  if (!m) throw new Error(`token --${name} is missing from the ${theme} theme`);
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

const SURFACES = ["page", "surface", "raised", "overlay"];
const STATUSES = ["passed", "running", "queued", "blocked", "failed", "escalated", "idle"];

describe("contrast calculator", () => {
  it("computes known ratios correctly", () => {
    expect(contrast("#000000", "#ffffff")).toBeCloseTo(21, 0);
    expect(contrast("#777777", "#ffffff")).toBeCloseTo(4.48, 1);
  });
});

describe.each(Object.keys(THEMES) as Theme[])("%s theme (WCAG 2.1 AA)", (theme) => {
  const t = (name: string) => token(theme, name);

  it("body, secondary and tertiary text and the accent meet 4.5:1 on every surface", () => {
    for (const fg of ["fg", "fg-2", "fg-3", "accent"]) {
      for (const bg of SURFACES) expect(contrast(t(fg), t(bg)), `${fg} on ${bg}`).toBeGreaterThanOrEqual(4.5);
    }
  });

  it("every status colour is readable on its chip and on every surface it is printed on", () => {
    for (const s of STATUSES) {
      expect(contrast(t(s), t(`${s}-bg`)), `${s} on its chip`).toBeGreaterThanOrEqual(4.5);
      for (const bg of SURFACES) expect(contrast(t(s), t(bg)), `${s} on ${bg}`).toBeGreaterThanOrEqual(4.5);
    }
  });

  it("the primary button gradient is readable at both ends", () => {
    for (const end of ["accent-from", "accent-to"]) expect(contrast(t("on-accent"), t(end)), end).toBeGreaterThanOrEqual(4.5);
  });

  it("the borders of inputs reach 3:1 so the controls can be found (WCAG 1.4.11)", () => {
    for (const bg of SURFACES) expect(contrast(t("control"), t(bg)), `control on ${bg}`).toBeGreaterThanOrEqual(3);
  });

  it("every status has a distinct colour, so the icon and the word are not the only difference", () => {
    expect(new Set(STATUSES.map((s) => t(s))).size).toBeGreaterThanOrEqual(6); // queued and idle are both neutral on purpose
  });
});

describe("type and fonts", () => {
  it("uses one UI font and one monospace font, 14px body text", () => {
    expect(css).toMatch(/--font-sans:/);
    expect(css).toMatch(/--font-mono:/);
    expect(css).toMatch(/font:\s*400 14px/);
  });

  it("has no text below 13px in any component", () => {
    const small = /text-\[(?:[0-9]|1[0-2])(?:\.\d+)?px\]/;
    for (const file of ["TopBar", "Sidebar", "AgentStepCard", "ActivityTimeline", "ResultCard", "PlanStepper", "TeamView", "Composer", "EventLogDrawer", "AttentionCard"]) {
      expect(readFileSync(new URL(`./components/${file}.tsx`, import.meta.url), "utf8"), file).not.toMatch(small);
    }
  });

  it("respects prefers-reduced-motion", () => {
    expect(css).toContain("prefers-reduced-motion: reduce");
  });
});
