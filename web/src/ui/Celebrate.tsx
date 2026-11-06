import { motion } from "framer-motion";
import { Check } from "lucide-react";
import { useMemo } from "react";

import { useReducedMotion } from "./bits";

const COLOURS = ["var(--passed)", "var(--accent)", "var(--running)", "var(--blocked)"];

/** A small check-and-confetti burst for a run that passes. Fires once on mount; with `burst` false, or under reduced motion, it is a still check. */
export function Celebrate({ burst = true }: { burst?: boolean }) {
  const reduce = useReducedMotion() || !burst;
  const pieces = useMemo(
    () => Array.from({ length: 20 }, (_, i) => {
      const angle = (i / 20) * Math.PI * 2 + (i % 2) * 0.15;
      const reach = 46 + (i % 5) * 9;
      return { x: Math.cos(angle) * reach, y: Math.sin(angle) * reach, r: (i * 47) % 360, c: COLOURS[i % COLOURS.length], round: i % 3 === 0 };
    }),
    [],
  );
  return (
    <span className="relative grid size-12 shrink-0 place-items-center" role="img" aria-label="Run passed">
      <motion.span
        className="grid size-12 place-items-center rounded-2xl bg-passed-bg text-passed shadow-[inset_0_0_0_1px_var(--passed)]"
        initial={reduce ? false : { scale: 0.4, opacity: 0 }} animate={{ scale: 1, opacity: 1 }} transition={{ type: "spring", stiffness: 380, damping: 18 }}
      >
        <Check size={26} strokeWidth={3} aria-hidden />
      </motion.span>
      {!reduce && pieces.map((p, i) => (
        <motion.span
          key={i} aria-hidden="true" className={`pointer-events-none absolute left-1/2 top-1/2 size-1.5 ${p.round ? "rounded-full" : "rounded-[2px]"}`} style={{ background: p.c }}
          initial={{ x: 0, y: 0, opacity: 1, scale: 1 }} animate={{ x: p.x, y: p.y, opacity: 0, scale: 0.4, rotate: p.r }} transition={{ duration: 0.9, ease: [0.2, 0.7, 0.2, 1] }}
        />
      ))}
    </span>
  );
}
