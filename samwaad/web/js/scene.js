// Samwaad 3D scene — an audio-reactive "voice orb" wrapped in a ring of Indian-language glyphs.
//
// Orb: high-detail icosphere, vertices pushed along their normals by two octaves of 3D simplex
// noise; amplitude follows the live audio level from the backend (WebSocket "level" events).
// Fragment: iridescent cosine palette + Fresnel rim, warming to saffron while someone speaks.
// Everything is bundled locally (vendor/three.module.min.js) so it works fully offline.

import * as THREE from "/static/vendor/three.module.min.js";

const NOISE = /* glsl */ `
vec3 mod289(vec3 x){return x-floor(x*(1.0/289.0))*289.0;}
vec4 mod289(vec4 x){return x-floor(x*(1.0/289.0))*289.0;}
vec4 permute(vec4 x){return mod289(((x*34.0)+10.0)*x);}
vec4 taylorInvSqrt(vec4 r){return 1.79284291400159-0.85373472095314*r;}
float snoise(vec3 v){
  const vec2 C=vec2(1.0/6.0,1.0/3.0); const vec4 D=vec4(0.0,0.5,1.0,2.0);
  vec3 i=floor(v+dot(v,C.yyy)); vec3 x0=v-i+dot(i,C.xxx);
  vec3 g=step(x0.yzx,x0.xyz); vec3 l=1.0-g; vec3 i1=min(g.xyz,l.zxy); vec3 i2=max(g.xyz,l.zxy);
  vec3 x1=x0-i1+C.xxx; vec3 x2=x0-i2+C.yyy; vec3 x3=x0-D.yyy;
  i=mod289(i);
  vec4 p=permute(permute(permute(i.z+vec4(0.0,i1.z,i2.z,1.0))+i.y+vec4(0.0,i1.y,i2.y,1.0))+i.x+vec4(0.0,i1.x,i2.x,1.0));
  float n_=0.142857142857; vec3 ns=n_*D.wyz-D.xzx;
  vec4 j=p-49.0*floor(p*ns.z*ns.z); vec4 x_=floor(j*ns.z); vec4 y_=floor(j-7.0*x_);
  vec4 x=x_*ns.x+ns.yyyy; vec4 y=y_*ns.x+ns.yyyy; vec4 h=1.0-abs(x)-abs(y);
  vec4 b0=vec4(x.xy,y.xy); vec4 b1=vec4(x.zw,y.zw);
  vec4 s0=floor(b0)*2.0+1.0; vec4 s1=floor(b1)*2.0+1.0; vec4 sh=-step(h,vec4(0.0));
  vec4 a0=b0.xzyw+s0.xzyw*sh.xxyy; vec4 a1=b1.xzyw+s1.xzyw*sh.zzww;
  vec3 p0=vec3(a0.xy,h.x); vec3 p1=vec3(a0.zw,h.y); vec3 p2=vec3(a1.xy,h.z); vec3 p3=vec3(a1.zw,h.w);
  vec4 norm=taylorInvSqrt(vec4(dot(p0,p0),dot(p1,p1),dot(p2,p2),dot(p3,p3)));
  p0*=norm.x; p1*=norm.y; p2*=norm.z; p3*=norm.w;
  vec4 m=max(0.5-vec4(dot(x0,x0),dot(x1,x1),dot(x2,x2),dot(x3,x3)),0.0); m=m*m;
  return 105.0*dot(m*m,vec4(dot(p0,x0),dot(p1,x1),dot(p2,x2),dot(p3,x3)));
}`;

const ORB_VERT = /* glsl */ `
uniform float uTime; uniform float uLevel;
varying vec3 vNormal; varying vec3 vView; varying float vDisp; varying vec3 vPos;
${NOISE}
float field(vec3 n){
  float a = 0.045 + uLevel * 0.2;
  return snoise(n * 1.1 + vec3(uTime * 0.2)) * a + snoise(n * 2.4 - vec3(uTime * 0.33)) * a * 0.3;
}
void main(){
  vec3 n = normalize(position);
  float d = field(n);
  vec3 p = position + normal * d;
  // perturbed normal from neighbouring samples so lighting follows the waves
  vec3 t = normalize(cross(n, abs(n.y) < 0.99 ? vec3(0.0, 1.0, 0.0) : vec3(1.0, 0.0, 0.0)));
  vec3 b = normalize(cross(n, t));
  float e = 0.02;
  vec3 pt = normalize(n + t * e); vec3 pb = normalize(n + b * e);
  vec3 P1 = pt * (1.0 + field(pt)); vec3 P2 = pb * (1.0 + field(pb)); vec3 P0 = n * (1.0 + d);
  vec3 nn = normalize(cross(P1 - P0, P2 - P0));
  if (dot(nn, n) < 0.0) nn = -nn;
  vec4 mv = modelViewMatrix * vec4(p, 1.0);
  vNormal = normalize(normalMatrix * nn);
  vView = normalize(-mv.xyz);
  vDisp = d; vPos = p;
  gl_Position = projectionMatrix * mv;
}`;

const ORB_FRAG = /* glsl */ `
uniform float uTime; uniform float uLevel; uniform float uSpeech; uniform float uDim;
varying vec3 vNormal; varying vec3 vView; varying float vDisp; varying vec3 vPos;
vec3 palette(float t){ // cosine palette: indigo -> cyan -> violet
  return vec3(0.52, 0.48, 0.70) + vec3(0.42, 0.40, 0.30) * cos(6.28318 * (vec3(1.0, 1.0, 0.9) * t + vec3(0.55, 0.30, 0.10)));
}
void main(){
  vec3 N = normalize(vNormal), V = normalize(vView);
  float fres = pow(1.0 - max(dot(N, V), 0.0), 2.4);
  float t = dot(N, vec3(0.3, 0.8, 0.5)) * 0.35 + vDisp * 1.6 + uTime * 0.04;
  vec3 col = palette(t);
  vec3 warm = mix(vec3(1.0, 0.56, 0.24), vec3(1.0, 0.33, 0.6), 0.5 + 0.5 * sin(uTime * 0.7 + vPos.y * 2.0));
  col = mix(col, warm, clamp(uSpeech, 0.0, 1.0) * 0.55);
  vec3 L = normalize(vec3(-0.4, 0.8, 0.6));
  float spec = pow(max(dot(reflect(-L, N), V), 0.0), 48.0);
  float diff = max(dot(N, L), 0.0);
  vec3 deep = vec3(0.17, 0.15, 0.46);                       // glassy indigo core
  vec3 c = mix(deep, col, 0.35 + 0.65 * fres) * (0.75 + 0.45 * diff);
  c += col * fres * 0.6 + vec3(1.0) * (spec * 0.85 + pow(fres, 6.0) * 0.45);
  c *= 0.95 + uLevel * 0.5;
  float a = (0.9 + fres * 0.1) * uDim;
  gl_FragColor = vec4(c * uDim, a);
}`;

const GLOW_FRAG = /* glsl */ `
uniform float uLevel; uniform float uSpeech; uniform float uDim;
varying vec3 vNormal; varying vec3 vView;
void main(){
  // back faces: -dot ≈ 0.76 right at the orb's silhouette, 0 at the halo's outer edge
  float i = pow(smoothstep(0.0, 0.78, -dot(normalize(vNormal), normalize(vView))), 3.0) * 0.55;
  vec3 cool = vec3(0.45, 0.52, 1.0), warm = vec3(1.0, 0.55, 0.35);
  vec3 c = mix(cool, warm, clamp(uSpeech, 0.0, 1.0) * 0.6) * i * (1.1 + uLevel * 1.6);
  gl_FragColor = vec4(c * uDim, i * uDim);
}`;
const GLOW_VERT = /* glsl */ `
varying vec3 vNormal; varying vec3 vView;
void main(){ vec4 mv = modelViewMatrix * vec4(position, 1.0); vNormal = normalize(normalMatrix * normal);
  vView = normalize(-mv.xyz); gl_Position = projectionMatrix * mv; }`;

// Scripts of India (+ a few friends) orbiting the orb
const GLYPHS = ["अ", "ம", "ক", "ગ", "ਸ", "ಕ", "മ", "తె", "ଓ", "ع", "A", "श", "த", "ব", "ज्ञा", "ళ"];

function glyphTexture(ch) {
  const c = document.createElement("canvas");
  c.width = c.height = 128;
  const g = c.getContext("2d");
  g.fillStyle = "#fff";
  g.font = `600 78px "Nirmala UI", "Noto Sans", "Segoe UI", sans-serif`;
  g.textAlign = "center";
  g.textBaseline = "middle";
  g.shadowColor = "rgba(160,180,255,.9)";
  g.shadowBlur = 18;
  g.fillText(ch, 64, 68);
  const t = new THREE.CanvasTexture(c);
  t.colorSpace = THREE.SRGBColorSpace;
  return t;
}

export function createScene(canvas, { glyphs = true } = {}) {
  let renderer;
  try {
    renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true, powerPreference: "low-power" });
  } catch (e) {
    console.warn("WebGL unavailable — 3D scene disabled", e);
    canvas.style.display = "none";
    const noop = () => {};
    return { follow: noop, setLevel: noop, setActive: noop, setDim: noop };
  }
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
  renderer.setClearColor(0x000000, 0);

  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(35, 1, 0.1, 100);
  camera.position.set(0, 0, 10);

  const uniforms = { uTime: { value: 0 }, uLevel: { value: 0 }, uSpeech: { value: 0 }, uDim: { value: 1 } };
  const rig = new THREE.Group();
  scene.add(rig);

  const orb = new THREE.Mesh(
    new THREE.IcosahedronGeometry(1, 48),
    new THREE.ShaderMaterial({ vertexShader: ORB_VERT, fragmentShader: ORB_FRAG, uniforms, transparent: true }),
  );
  rig.add(orb);

  const glow = new THREE.Mesh(
    new THREE.SphereGeometry(1.5, 48, 48),
    new THREE.ShaderMaterial({ vertexShader: GLOW_VERT, fragmentShader: GLOW_FRAG, uniforms, transparent: true,
                               side: THREE.BackSide, blending: THREE.AdditiveBlending, depthWrite: false }),
  );
  rig.add(glow);

  const shell = new THREE.LineSegments(
    new THREE.WireframeGeometry(new THREE.IcosahedronGeometry(1.42, 2)),
    new THREE.LineBasicMaterial({ color: 0xa9b6ff, transparent: true, opacity: 0.09, depthWrite: false }),
  );
  rig.add(shell);

  // glyph ring
  const ring = new THREE.Group();
  ring.rotation.set(1.15, 0, -0.28);
  const sprites = [];
  if (glyphs) {
    GLYPHS.forEach((ch, i) => {
      const s = new THREE.Sprite(new THREE.SpriteMaterial({ map: glyphTexture(ch), transparent: true, depthWrite: false,
                                                            opacity: 0.6, blending: THREE.AdditiveBlending }));
      s.userData = { a: (i / GLYPHS.length) * Math.PI * 2, r: 2.05 + (i % 3) * 0.16, bob: Math.random() * 6 };
      s.scale.setScalar(0.34);
      ring.add(s);
      sprites.push(s);
    });
  }
  // orbit line
  const orbit = new THREE.Mesh(
    new THREE.TorusGeometry(2.2, 0.004, 8, 200),
    new THREE.MeshBasicMaterial({ color: 0x9fb2ff, transparent: true, opacity: 0.18, depthWrite: false }),
  );
  ring.add(orbit);
  rig.add(ring);

  // star dust (screen-wide, not tied to the orb)
  const N = 900, pos = new Float32Array(N * 3);
  for (let i = 0; i < N; i++) {
    const r = 6 + Math.random() * 14, th = Math.random() * Math.PI * 2, ph = Math.acos(2 * Math.random() - 1);
    pos.set([r * Math.sin(ph) * Math.cos(th), r * Math.sin(ph) * Math.sin(th), -Math.abs(r * Math.cos(ph)) - 2], i * 3);
  }
  const dustGeo = new THREE.BufferGeometry();
  dustGeo.setAttribute("position", new THREE.BufferAttribute(pos, 3));
  const dust = new THREE.Points(dustGeo, new THREE.PointsMaterial({ size: 0.035, color: 0xcfd8ff, transparent: true,
                                                                     opacity: 0.55, depthWrite: false }));
  scene.add(dust);

  // ---------------------------------------------------------------- state
  let anchor = null, targetLevel = 0, level = 0, targetSpeech = 0, speech = 0, active = false, dim = 1, targetDim = 1;
  const target = { x: 0, y: 0, s: 1 };
  const mouse = { x: 0, y: 0 };
  window.addEventListener("pointermove", (e) => {
    mouse.x = e.clientX / innerWidth - 0.5;
    mouse.y = e.clientY / innerHeight - 0.5;
  }, { passive: true });

  function resize() {
    const w = innerWidth, h = innerHeight;
    renderer.setSize(w, h, false);
    camera.aspect = w / h;
    camera.updateProjectionMatrix();
  }
  addEventListener("resize", resize);
  resize();

  function place() {
    const vh = 2 * Math.tan(THREE.MathUtils.degToRad(camera.fov / 2)) * camera.position.z;
    const vw = vh * camera.aspect;
    if (!anchor || !anchor.isConnected) return;
    const r = anchor.getBoundingClientRect();
    if (!r.width) return;
    target.x = ((r.left + r.width / 2) / innerWidth - 0.5) * vw;
    target.y = -((r.top + r.height / 2) / innerHeight - 0.5) * vh;
    target.s = ((Math.min(r.width, r.height) / innerHeight) * vh) / 4.2; // ring (r≈2.3) fits the anchor
  }

  const clock = new THREE.Clock();
  let first = true;
  function frame() {
    const dt = Math.min(clock.getDelta(), 0.05), t = clock.elapsedTime;
    place();
    const k = first ? 1 : 1 - Math.pow(0.001, dt);         // frame-rate independent easing
    first = false;
    rig.position.x += (target.x - rig.position.x) * k;
    rig.position.y += (target.y - rig.position.y) * k;
    const s = rig.scale.x + (target.s - rig.scale.x) * k;
    rig.scale.setScalar(s);

    targetLevel *= Math.pow(0.25, dt);                      // decays if the stream goes quiet
    targetSpeech *= Math.pow(0.4, dt);
    const idle = 0.05 + 0.03 * Math.sin(t * 1.3);
    level += (Math.max(targetLevel, idle) - level) * Math.min(1, dt * 9);
    speech += (targetSpeech - speech) * Math.min(1, dt * 5);
    dim += (targetDim - dim) * Math.min(1, dt * 4);

    uniforms.uTime.value = t;
    uniforms.uLevel.value = level;
    uniforms.uSpeech.value = speech;
    uniforms.uDim.value = dim;

    orb.rotation.y += dt * (0.12 + level * 0.6);
    shell.rotation.y -= dt * 0.05;
    shell.rotation.x += dt * 0.02;
    shell.material.opacity = (0.07 + level * 0.25) * dim;
    ring.rotation.z += dt * (active ? 0.22 : 0.09);
    for (const sp of sprites) {
      const { a, r, bob } = sp.userData;
      sp.position.set(Math.cos(a) * r, Math.sin(a) * r, Math.sin(t * 0.8 + bob) * 0.12);
      sp.material.opacity = (0.42 + level * 0.9 + 0.12 * Math.sin(t * 1.7 + bob)) * dim;
      sp.scale.setScalar(0.3 + level * 0.12);
    }
    orbit.material.opacity = (0.12 + level * 0.3) * dim;
    rig.rotation.x += ((mouse.y * 0.25) - rig.rotation.x) * 0.05;
    rig.rotation.y += ((mouse.x * 0.35) - rig.rotation.y) * 0.05;
    dust.rotation.y = t * 0.006 + mouse.x * 0.05;
    dust.rotation.x = mouse.y * 0.03;

    renderer.render(scene, camera);
    requestAnimationFrame(frame);
  }
  requestAnimationFrame(frame);

  return {
    /** Park the orb over a DOM element; it glides there and scales to fit. */
    follow(el) { anchor = el; },
    setLevel(rms, sp = 0) { targetLevel = Math.max(targetLevel, Math.min(1, rms)); targetSpeech = Math.max(targetSpeech, sp); },
    setActive(on) { active = on; },
    setDim(v) { targetDim = v; },
  };
}
