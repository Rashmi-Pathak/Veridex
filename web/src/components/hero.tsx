"use client";

import { motion } from "motion/react";

import { MetricsRibbon } from "./metrics-ribbon";

// The hero. A staggered page-load reveal over the (now bloomed) galaxy: eyebrow, the thesis as a
// large confident headline with the recovered thing in the signal color, the one-line description,
// then the live-metrics ribbon so the system visibly breathes from the first frame. Motion respects
// the app-level MotionConfig reducedMotion="user", so under reduce-motion the transforms drop.
const item = {
  hidden: { opacity: 0, y: 14 },
  show: { opacity: 1, y: 0, transition: { duration: 0.55, ease: [0.16, 1, 0.3, 1] as const } },
};

export function Hero() {
  return (
    <motion.header
      initial="hidden"
      animate="show"
      variants={{ hidden: {}, show: { transition: { staggerChildren: 0.09, delayChildren: 0.04 } } }}
      className="space-y-5"
    >
      <motion.p
        variants={item}
        className="font-mono text-xs uppercase tracking-[0.4em] text-emerald-300/70"
      >
        Veridex · open C2PA recovery
      </motion.p>

      <motion.h1
        variants={item}
        className="text-balance text-5xl font-semibold leading-[1.04] tracking-tight sm:text-6xl"
      >
        Recover stripped <span className="text-emerald-300">C2PA provenance</span>.
      </motion.h1>

      <motion.p variants={item} className="max-w-xl text-pretty text-white/60">
        A vendor-neutral C2PA Soft Binding Resolution server on Backblaze B2. It matches an invisible
        watermark or a perceptual-hash fingerprint to return the recovered, signed manifest, with a
        tamper-evident transparency-log proof. Provenance proves origin, not truth.
      </motion.p>

      <motion.div variants={item}>
        <MetricsRibbon />
      </motion.div>
    </motion.header>
  );
}
