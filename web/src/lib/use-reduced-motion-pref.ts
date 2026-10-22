"use client";

import { useReducedMotion } from "motion/react";

// One source of truth for the OS "reduce motion" setting, used to gate the R3F frameloop, the WebGL
// backdrop, and (via MotionConfig) the DOM transitions. Motion's hook is reactive (re-renders on the
// setting changing) and returns boolean | null (null before hydration); treat null as "do not
// reduce" so the scene animates by default and only stops when the user has explicitly asked.
export function usePrefersReducedMotion(): boolean {
  return useReducedMotion() ?? false;
}
