// Radial audio spectrum around the orb — 72 bars driven by the 16 loudness bands the
// pipeline streams (~16×/s). Mirrored left/right so it reads as one symmetric "voice halo".
export function createRing(canvas, anchor) {
  const ctx = canvas.getContext("2d");
  const N = 72;
  let bands = new Array(16).fill(0), cur = new Float32Array(N), speech = 0, active = false, raf = 0, t = 0;

  function size() {
    const r = anchor.getBoundingClientRect(), s = Math.round(Math.min(r.width, r.height) * 1.34), dpr = Math.min(devicePixelRatio, 2);
    canvas.style.width = canvas.style.height = `${s}px`;
    canvas.width = canvas.height = s * dpr;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    return s;
  }
  let S = size();
  new ResizeObserver(() => { S = size(); }).observe(anchor);

  function target(i) {
    // map bar i (0..N) onto mirrored bands: top = low freqs, bottom = highs
    const half = N / 2, k = i < half ? i / half : (N - i) / half;
    const f = k * (bands.length - 1), a = Math.floor(f), b = Math.min(bands.length - 1, a + 1), w = f - a;
    return bands[a] * (1 - w) + bands[b] * w;
  }

  function draw() {
    t += 1 / 60;
    ctx.clearRect(0, 0, S, S);
    const c = S / 2, r0 = S * 0.36, maxL = S * 0.12;
    for (let i = 0; i < N; i++) {
      const goal = active ? target(i) : 0.05 + 0.03 * Math.sin(t * 1.4 + i * 0.35);
      cur[i] += (goal - cur[i]) * (goal > cur[i] ? 0.45 : 0.12);
      const a = (i / N) * Math.PI * 2 - Math.PI / 2, len = 3 + cur[i] * maxL;
      const x1 = c + Math.cos(a) * r0, y1 = c + Math.sin(a) * r0, x2 = c + Math.cos(a) * (r0 + len), y2 = c + Math.sin(a) * (r0 + len);
      const hue = speech > 0.5 ? 28 + 30 * (i / N) : 230 + 60 * Math.sin((i / N) * Math.PI);
      ctx.strokeStyle = `hsla(${hue}, 95%, ${speech > 0.5 ? 68 : 72}%, ${0.25 + cur[i] * 0.75})`;
      ctx.lineWidth = Math.max(2, S / 180);
      ctx.lineCap = "round";
      ctx.beginPath();
      ctx.moveTo(x1, y1);
      ctx.lineTo(x2, y2);
      ctx.stroke();
    }
    raf = requestAnimationFrame(draw);
  }
  raf = requestAnimationFrame(draw);

  return {
    set(b, sp) { if (b && b.length) bands = b; speech = sp || 0; },
    setActive(on) { active = on; if (!on) bands = bands.map(() => 0); },
    stop() { cancelAnimationFrame(raf); },
  };
}
