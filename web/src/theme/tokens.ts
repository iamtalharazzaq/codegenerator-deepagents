/** The theme token file. Colours live in styles.css (so both themes and the WCAG test read one source); this file holds
 * everything else that has to be shared: the status vocabulary, the agent identities, the scales and the motion presets. */

import {
  Ban, Braces, Briefcase, CircleCheck, CircleDashed, CircleX, Clock, Compass, Database, FlaskConical, ListChecks, LoaderCircle, Monitor,
  Network, Palette, ScanSearch, Server, TriangleAlert, type LucideIcon,
} from "lucide-react";

import type { UiStatus } from "../model";

/** One status system: a colour, an icon and a word. The icon shape and the word carry the meaning, never colour alone.
 * Class names are written out in full so Tailwind can see them. */
export interface StatusToken {
  label: string;
  icon: LucideIcon;
  /** a sentence for screen readers */
  aria: string;
  text: string;
  chip: string;
  ring: string;
  dot: string;
  tone: string; // a CSS colour for SVG strokes
  spin?: boolean;
}

export const STATUS: Record<UiStatus, StatusToken> = {
  passed: { label: "Passed", icon: CircleCheck, aria: "Passed", text: "text-passed", chip: "bg-passed-bg text-passed", ring: "border-passed/40", dot: "bg-passed", tone: "var(--passed)" },
  running: { label: "Running", icon: LoaderCircle, aria: "Running", text: "text-running", chip: "bg-running-bg text-running", ring: "border-running/50", dot: "bg-running", tone: "var(--running)", spin: true },
  queued: { label: "Queued", icon: Clock, aria: "Queued, waiting its turn", text: "text-queued", chip: "bg-queued-bg text-queued", ring: "border-hairline", dot: "bg-queued", tone: "var(--queued)" },
  blocked: { label: "Blocked", icon: Ban, aria: "Blocked, waiting on something else", text: "text-blocked", chip: "bg-blocked-bg text-blocked", ring: "border-blocked/40", dot: "bg-blocked", tone: "var(--blocked)" },
  failed: { label: "Failed", icon: CircleX, aria: "Failed", text: "text-failed", chip: "bg-failed-bg text-failed", ring: "border-failed/40", dot: "bg-failed", tone: "var(--failed)" },
  escalated: { label: "Escalated", icon: TriangleAlert, aria: "Escalated, needs your attention", text: "text-escalated", chip: "bg-escalated-bg text-escalated", ring: "border-escalated/50", dot: "bg-escalated", tone: "var(--escalated)" },
  idle: { label: "Not needed", icon: CircleDashed, aria: "Not needed for this run", text: "text-idle", chip: "bg-idle-bg text-idle", ring: "border-hairline", dot: "bg-idle", tone: "var(--idle)" },
};

export const STATUS_ORDER = Object.keys(STATUS) as UiStatus[];

/** Every agent has one icon and one hue, used in the timeline, the plan, the graph and the drawer. */
export interface AgentToken {
  label: string;
  short: string;
  icon: LucideIcon;
  hue: number;
}

export const AGENTS: Record<string, AgentToken> = {
  project_manager: { label: "Project Manager", short: "PM", icon: Compass, hue: 252 },
  business_analyst: { label: "Business Analyst", short: "Analyst", icon: Briefcase, hue: 32 },
  product_manager: { label: "Product Manager", short: "Product", icon: ListChecks, hue: 328 },
  solution_architect: { label: "Solution Architect", short: "Architect", icon: Network, hue: 200 },
  code_analyst: { label: "Code Analyst", short: "Code", icon: ScanSearch, hue: 168 },
  database_engineer: { label: "Database Engineer", short: "Database", icon: Database, hue: 48 },
  backend_developer: { label: "Backend Developer", short: "Backend", icon: Braces, hue: 150 },
  frontend_developer: { label: "Frontend Developer", short: "Frontend", icon: Monitor, hue: 284 },
  ui_ux_designer: { label: "UI/UX Designer", short: "Design", icon: Palette, hue: 350 },
  qa_engineer: { label: "QA Engineer", short: "QA", icon: FlaskConical, hue: 18 },
  devops_engineer: { label: "DevOps Engineer", short: "DevOps", icon: Server, hue: 218 },
};

const FALLBACK: AgentToken = { label: "Agent", short: "Agent", icon: Compass, hue: 220 };
export const agentToken = (role: string): AgentToken => AGENTS[role] ?? { ...FALLBACK, label: role };

/** Type scale (px / line-height). Body is 14, content that is read for its own sake is 15, meta never goes below 13. */
export const TYPE_SCALE = { meta: "13px/20px", body: "14px/22px", content: "15px/25px", title: "17px/24px", display: "22px/28px" } as const;
/** Spacing scale in px: the 8px rhythm plus the 4px half-step for tight gaps. */
export const SPACING = [4, 8, 12, 16, 24, 32, 48] as const;
export const RADIUS = { control: 12, card: 16, pill: 9999 } as const;

/** Motion presets shared by every animated component. Durations are in seconds. */
export const MOTION = {
  fast: { duration: 0.15, ease: [0.2, 0, 0, 1] },
  base: { duration: 0.24, ease: [0.2, 0, 0, 1] },
  spring: { type: "spring", stiffness: 420, damping: 36 },
} as const;
