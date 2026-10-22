import { useMemo, useRef } from "react";
import { useFrame, useThree } from "@react-three/fiber";
import * as THREE from "three";

const COUNT = 9000;
const ARMS = 3;
const RADIUS = 5;
const SPIN = 1.1;
const RANDOMNESS = 0.35;
const INNER = new THREE.Color("#ff8a3d"); // warm core
const OUTER = new THREE.Color("#3b6dff"); // cool rim (Backblaze-ish blue)
// Sparse accent tints scattered through the arms so the field reads alive, not two-toned:
// pink and ember stars keep the palette the site already had, emerald ties the backdrop to the
// brand's VERIFIED green. Probabilities are small so the spiral's warm-to-cool read survives.
const PINK = new THREE.Color("#ff6ba8");
const EMBER = new THREE.Color("#ff4545");
const EMERALD = new THREE.Color("#34d399");

// A spiral galaxy of shader point sprites. Positions, colors, sizes, and per-point seeds are
// computed once; per-frame work is a slow Y rotation plus a time uniform for the twinkle.
function buildGalaxy() {
  const positions = new Float32Array(COUNT * 3);
  const colors = new Float32Array(COUNT * 3);
  const sizes = new Float32Array(COUNT);
  const seeds = new Float32Array(COUNT);
  for (let i = 0; i < COUNT; i++) {
    const i3 = i * 3;
    const radius = Math.pow(Math.random(), 1.5) * RADIUS;
    const branch = ((i % ARMS) / ARMS) * Math.PI * 2;
    const spin = radius * SPIN;
    const spread = () =>
      Math.pow(Math.random(), 3) * (Math.random() < 0.5 ? 1 : -1) * RANDOMNESS * radius;

    positions[i3] = Math.cos(branch + spin) * radius + spread();
    positions[i3 + 1] = spread() * 0.5;
    positions[i3 + 2] = Math.sin(branch + spin) * radius + spread();

    const mixed = INNER.clone().lerp(OUTER, radius / RADIUS);
    // Sparse accent tints, blended (not replaced) so accents still sit in the spiral's gradient.
    const roll = Math.random();
    if (roll < 0.1) mixed.lerp(PINK, 0.75);
    else if (roll < 0.14) mixed.lerp(EMBER, 0.7);
    else if (roll < 0.18) mixed.lerp(EMERALD, 0.7);

    // Size variance sells depth: mostly small, a long tail of brighter stars, and ~2% hero orbs
    // that carry the bloom. Hero orbs get whitened cores so they glow instead of clip.
    const isHero = Math.random() < 0.02;
    sizes[i] = isHero ? 0.085 + Math.random() * 0.05 : 0.018 + Math.pow(Math.random(), 2.2) * 0.04;
    if (isHero) mixed.lerp(new THREE.Color("#ffffff"), 0.35);

    colors[i3] = mixed.r;
    colors[i3 + 1] = mixed.g;
    colors[i3 + 2] = mixed.b;
    seeds[i] = Math.random();
  }
  return { positions, colors, sizes, seeds };
}

// Point sprites with a real light falloff: a hot core (cubic) inside a soft halo, so each star
// reads as a glowing orb instead of a hard square-edged dot, and the bloom pass has genuine
// bright centers to feed on. The twinkle modulates size a few percent per star, phase-shifted by
// its seed; uTime stays 0 under reduced motion so the field is static there.
const VERTEX = /* glsl */ `
attribute float aSize;
attribute float aSeed;
uniform float uTime;
uniform float uScale;
varying vec3 vColor;
void main() {
  vColor = color;
  vec4 mv = modelViewMatrix * vec4(position, 1.0);
  float twinkle = 0.88 + 0.12 * sin(uTime * (0.5 + fract(aSeed * 7.13) * 1.6) + aSeed * 6.2831);
  gl_PointSize = max(aSize * uScale * twinkle / -mv.z, 1.0);
  gl_Position = projectionMatrix * mv;
}
`;

const FRAGMENT = /* glsl */ `
varying vec3 vColor;
void main() {
  float d = length(gl_PointCoord - 0.5) * 2.0;
  if (d > 1.0) discard;
  float core = pow(max(1.0 - d, 0.0), 3.0);
  float halo = pow(max(1.0 - d, 0.0), 1.3) * 0.32;
  gl_FragColor = vec4(vColor * (0.7 + core * 1.5), core + halo);
}
`;

export function Galaxy({ reduced }: { reduced: boolean }) {
  const ref = useRef<THREE.Points>(null);
  const material = useRef<THREE.ShaderMaterial>(null);
  const { positions, colors, sizes, seeds } = useMemo(buildGalaxy, []);
  const size = useThree((s) => s.size);

  const uniforms = useMemo(
    () => ({ uTime: { value: 0 }, uScale: { value: 400 } }),
    [],
  );
  // sizeAttenuation by hand: world size -> pixels needs half the canvas height in the scale.
  uniforms.uScale.value = size.height * 0.5 * 2.2;

  useFrame((_, delta) => {
    if (reduced) return;
    if (ref.current) ref.current.rotation.y += delta * 0.04;
    if (material.current) material.current.uniforms.uTime.value += delta;
  });

  return (
    <points ref={ref} rotation={[0.5, 0, 0]} frustumCulled={false}>
      <bufferGeometry>
        <bufferAttribute attach="attributes-position" args={[positions, 3]} />
        <bufferAttribute attach="attributes-color" args={[colors, 3]} />
        <bufferAttribute attach="attributes-aSize" args={[sizes, 1]} />
        <bufferAttribute attach="attributes-aSeed" args={[seeds, 1]} />
      </bufferGeometry>
      <shaderMaterial
        ref={material}
        vertexShader={VERTEX}
        fragmentShader={FRAGMENT}
        uniforms={uniforms}
        vertexColors
        transparent
        depthWrite={false}
        blending={THREE.AdditiveBlending}
      />
    </points>
  );
}
