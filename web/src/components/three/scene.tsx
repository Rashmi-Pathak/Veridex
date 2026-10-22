"use client";

import { Canvas, useFrame, useThree } from "@react-three/fiber";
import { PerformanceMonitor } from "@react-three/drei";
import { Bloom, EffectComposer } from "@react-three/postprocessing";
import { useState } from "react";

import { usePrefersReducedMotion } from "@/lib/use-reduced-motion-pref";
import { Atmosphere } from "./atmosphere";
import { Dust } from "./dust";
import { Galaxy } from "./galaxy";

// A tiny parallax rig: the camera leans a fraction of a unit toward the pointer, re-aiming at the
// galaxy each frame. The offset is small enough to stay subliminal; what registers is that the
// scene has depth, because the near dust, the galaxy, and the atmosphere plane shear against each
// other. On narrow viewports the camera also eases back, so the dense galactic core shrinks out
// of the way of the hero text instead of burning through it. Inert under reduced motion.
function ParallaxRig({ reduced }: { reduced: boolean }) {
  const { camera, pointer, size } = useThree();
  const targetZ = size.width < 640 ? 10.4 : 7;
  useFrame(() => {
    if (reduced) return;
    camera.position.x += (pointer.x * 0.4 - camera.position.x) * 0.03;
    camera.position.y += (1.5 + pointer.y * 0.2 - camera.position.y) * 0.03;
    camera.position.z += (targetZ - camera.position.z) * 0.05;
    camera.lookAt(0, 0.3, 0);
  });
  return null;
}

// On phones the whole star stage also sinks a little, so the brightest region sits behind the
// first glass panel rather than behind the headline paragraph.
function Stage({ children }: { children: React.ReactNode }) {
  const width = useThree((s) => s.size.width);
  return <group position={width < 640 ? [0, -1.6, -2.2] : [0, 0, 0]}>{children}</group>;
}

// The single persistent Canvas: a fixed, full-screen, non-interactive backdrop behind the DOM. It
// lives in the root layout (a sibling of {children}) so it never unmounts across navigation. The
// functional UI is plain DOM on top of this, so the recovery result never depends on WebGL health
// (the demo-safe rule). Under reduced motion the frameloop is "demand": one static render, no loop.
// Scene layers, back to front: the atmosphere plane (ground ridge + emerald aurora), the galaxy
// point field, and the near dust; bloom lifts the bright orb cores into glow.
export function Scene() {
  const reduced = usePrefersReducedMotion();
  const [dpr, setDpr] = useState(1.5);

  return (
    <div className="pointer-events-none fixed inset-0 -z-10" aria-hidden="true">
      <Canvas
        dpr={dpr}
        frameloop={reduced ? "demand" : "always"}
        camera={{ position: [0, 1.5, 7], fov: 60 }}
        gl={{ antialias: false, powerPreference: "high-performance" }}
      >
        {/* Drop pixel ratio on weak devices, raise it on strong ones, to hold framerate. */}
        <PerformanceMonitor onIncline={() => setDpr(2)} onDecline={() => setDpr(1)} />
        <Atmosphere reduced={reduced} />
        <Stage>
          <Galaxy reduced={reduced} />
          <Dust reduced={reduced} />
        </Stage>
        <ParallaxRig reduced={reduced} />
        {/* Bloom turns the additive starfield into a glowing nebula. Off under reduced motion (and
            the backdrop renders a static gradient there anyway). multisampling 0 to match the
            antialias-off Canvas; mipmapBlur is the cheap blur so the effect holds framerate. */}
        {!reduced && (
          <EffectComposer multisampling={0}>
            <Bloom
              intensity={0.9}
              luminanceThreshold={0.1}
              luminanceSmoothing={0.9}
              radius={0.72}
              mipmapBlur
            />
          </EffectComposer>
        )}
      </Canvas>
    </div>
  );
}
