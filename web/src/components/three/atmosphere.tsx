import { useMemo, useRef } from "react";
import { useFrame, useThree } from "@react-three/fiber";
import * as THREE from "three";

// The atmosphere plane: one viewport-filling quad, one draw call, drawn before everything else.
// Its fragment shader composes the two grounding layers the flat-black backdrop lacked:
//  - a dark ground-ridge silhouette along the foot of the view (a 1D fbm heightline), and
//  - an emerald aurora that breathes above the ridge (an fbm-displaced glow band, the same
//    technique class nk.studio uses for its sky glare, implemented from scratch here).
// The aurora is the brand signal made physical: the exact green of every VERIFIED badge, rising
// off the horizon the galaxy hangs above. Time advances only when motion is allowed.
const VERTEX = /* glsl */ `
varying vec2 vUv;
void main() {
  vUv = uv;
  gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
}
`;

const FRAGMENT = /* glsl */ `
precision highp float;

varying vec2 vUv;
uniform float uTime;
uniform vec3 uAuroraLow;
uniform vec3 uAuroraHigh;
uniform vec3 uGround;

// Cheap value-noise fbm (3 octaves): plenty of organic wander for a background layer at a
// fraction of the cost of simplex, so the whole plane stays cheap at dpr 2.
float hash(vec2 p) {
  return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453123);
}
float vnoise(vec2 p) {
  vec2 i = floor(p);
  vec2 f = fract(p);
  vec2 u = f * f * (3.0 - 2.0 * f);
  return mix(
    mix(hash(i), hash(i + vec2(1.0, 0.0)), u.x),
    mix(hash(i + vec2(0.0, 1.0)), hash(i + vec2(1.0, 1.0)), u.x),
    u.y
  ) * 2.0 - 1.0;
}
float fbm(vec2 p) {
  return 0.55 * vnoise(p) + 0.28 * vnoise(p * 2.13 + 7.3) + 0.17 * vnoise(p * 4.31 + 3.1);
}

void main() {
  vec2 uv = vUv;
  float t = uTime * 0.05;

  // Ground ridge: a still heightline near the foot of the view. Slightly translucent so the
  // brightest bloomed stars shimmer through the silhouette edge.
  float ridge = 0.075 + 0.05 * fbm(vec2(uv.x * 3.1, 1.7));
  float ground = 1.0 - smoothstep(ridge - 0.004, ridge + 0.008, uv.y);

  // Aurora: a glow band whose centerline wanders with drifting fbm. A tight bright core plus a
  // wide soft haze, fading at the screen edges and dying out upward into the starfield. It hugs
  // the ridge (the backdrop is fixed, so content scrolls over it: the band stays low and soft
  // enough that panel text never has to fight it).
  float n = fbm(vec2(uv.x * 2.0 + t * 1.7, uv.y * 1.3 - t));
  float center = 0.125 + 0.125 * n;
  float d = abs(uv.y - center);
  float core = pow(max(1.0 - d * 4.8, 0.0), 3.0);
  float haze = pow(max(1.0 - d * 1.6, 0.0), 2.0) * 0.26;
  float edgeFade = smoothstep(0.0, 0.14, uv.x) * smoothstep(1.0, 0.86, uv.x);
  float skyFade = 1.0 - smoothstep(0.26, 0.55, uv.y);
  float aurora = (core * (0.5 + 0.35 * (0.5 + 0.5 * n)) + haze) * edgeFade * skyFade;

  vec3 col = mix(uAuroraLow, uAuroraHigh, clamp(uv.y * 2.6, 0.0, 1.0)) * aurora;
  float alpha = clamp(aurora, 0.0, 1.0) * 0.52;

  // The ridge silhouettes over the aurora, so the glare reads as rising from behind the ground.
  col = mix(col, uGround, ground);
  alpha = max(alpha, ground * 0.93);

  gl_FragColor = vec4(col, alpha);
}
`;

export function Atmosphere({ reduced }: { reduced: boolean }) {
  const material = useRef<THREE.ShaderMaterial>(null);
  const { viewport, camera } = useThree();
  // Size the quad to exactly fill the view at its depth, re-measured on every resize render.
  const v = viewport.getCurrentViewport(camera, new THREE.Vector3(0, 0, -4));

  const uniforms = useMemo(
    () => ({
      uTime: { value: 0 },
      uAuroraLow: { value: new THREE.Color("#0e9f6e") },
      uAuroraHigh: { value: new THREE.Color("#5efbd2") },
      uGround: { value: new THREE.Color("#03110f") },
    }),
    [],
  );

  useFrame((_, delta) => {
    if (!reduced && material.current) material.current.uniforms.uTime.value += delta;
  });

  return (
    <mesh position={[0, 0, -4]} scale={[v.width, v.height, 1]} renderOrder={-1}>
      <planeGeometry args={[1, 1]} />
      <shaderMaterial
        ref={material}
        vertexShader={VERTEX}
        fragmentShader={FRAGMENT}
        uniforms={uniforms}
        transparent
        depthWrite={false}
        depthTest={false}
      />
    </mesh>
  );
}
