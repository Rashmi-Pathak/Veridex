import { useMemo, useRef } from "react";
import { useFrame, useThree } from "@react-three/fiber";
import * as THREE from "three";

// Near-field dust: a sparse layer of large, very faint motes drifting slowly upward between the
// camera and the galaxy. It is the depth cue the scene was missing: the parallax between crisp
// distant stars and soft close motes makes the void read as air, not as a flat black wall.
const COUNT = 110;
const BOX = { x: 9, yMin: -4, yMax: 5, zMin: -2, zMax: 3.5 };
const BLUE = new THREE.Color("#9fb6ff");
const EMERALD = new THREE.Color("#34d399");

function buildDust() {
  const positions = new Float32Array(COUNT * 3);
  const colors = new Float32Array(COUNT * 3);
  const sizes = new Float32Array(COUNT);
  const seeds = new Float32Array(COUNT);
  for (let i = 0; i < COUNT; i++) {
    const i3 = i * 3;
    positions[i3] = (Math.random() * 2 - 1) * BOX.x;
    positions[i3 + 1] = BOX.yMin + Math.random() * (BOX.yMax - BOX.yMin);
    positions[i3 + 2] = BOX.zMin + Math.random() * (BOX.zMax - BOX.zMin);
    const tint = (Math.random() < 0.22 ? EMERALD : BLUE).clone();
    colors[i3] = tint.r;
    colors[i3 + 1] = tint.g;
    colors[i3 + 2] = tint.b;
    sizes[i] = 0.09 + Math.random() * 0.14;
    seeds[i] = Math.random();
  }
  return { positions, colors, sizes, seeds };
}

// The drift lives in the vertex shader (a wrapped upward mod on y plus a slow sideways sway), so
// the buffer is never rewritten. Alpha is kept very low: dust should be felt, not noticed.
const VERTEX = /* glsl */ `
attribute float aSize;
attribute float aSeed;
uniform float uTime;
uniform float uScale;
varying vec3 vColor;
varying float vFade;
void main() {
  vColor = color;
  vec3 p = position;
  float span = ${(BOX.yMax - BOX.yMin).toFixed(1)};
  float y = mod(p.y - ${BOX.yMin.toFixed(1)} + uTime * (0.04 + aSeed * 0.05), span);
  vFade = smoothstep(0.0, 0.12, y / span) * (1.0 - smoothstep(0.85, 1.0, y / span));
  p.y = y + ${BOX.yMin.toFixed(1)};
  p.x += sin(uTime * (0.05 + aSeed * 0.08) + aSeed * 6.2831) * 0.35;
  vec4 mv = modelViewMatrix * vec4(p, 1.0);
  gl_PointSize = max(aSize * uScale / -mv.z, 1.0);
  gl_Position = projectionMatrix * mv;
}
`;

const FRAGMENT = /* glsl */ `
varying vec3 vColor;
varying float vFade;
void main() {
  float d = length(gl_PointCoord - 0.5) * 2.0;
  if (d > 1.0) discard;
  float soft = pow(max(1.0 - d, 0.0), 2.0);
  gl_FragColor = vec4(vColor, soft * 0.16 * vFade);
}
`;

export function Dust({ reduced }: { reduced: boolean }) {
  const material = useRef<THREE.ShaderMaterial>(null);
  const { positions, colors, sizes, seeds } = useMemo(buildDust, []);
  const size = useThree((s) => s.size);

  const uniforms = useMemo(() => ({ uTime: { value: 0 }, uScale: { value: 400 } }), []);
  uniforms.uScale.value = size.height * 0.5 * 2.2;

  useFrame((_, delta) => {
    if (!reduced && material.current) material.current.uniforms.uTime.value += delta;
  });

  return (
    <points frustumCulled={false}>
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
