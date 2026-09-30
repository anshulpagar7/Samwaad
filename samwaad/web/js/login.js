import { hydrateIcons } from "./icons.js";
import { applyLiquidGlass, tilt } from "./liquidglass.js";
import { createScene } from "./scene.js";

const $ = (id) => document.getElementById(id);
hydrateIcons();
const scene = createScene($("scene"));
scene.follow($("orbAnchor"));
applyLiquidGlass();
tilt($("authCard"), 3);

// The orb "listens" to typing — a small taste of the live view.
document.addEventListener("keydown", () => scene.setLevel(0.3 + Math.random() * 0.25, 0.4));

let mode = "login";
const copy = {
  login: ["Welcome back", "Sign in to find your lectures, notes and flashcards.", "Sign in"],
  register: ["Create your account", "Takes 10 seconds. Stored only on this laptop.", "Create account"],
};

function moveThumb() {
  const seg = $("modeSeg"), b = seg.querySelector("button.on"), th = seg.querySelector(".thumb");
  th.style.width = `${b.offsetWidth}px`;
  th.style.transform = `translateX(${b.offsetLeft - 4}px)`;
}

function setMode(m) {
  mode = m;
  document.body.classList.toggle("register", m === "register");
  document.querySelectorAll("#modeSeg button").forEach((b) => { b.classList.toggle("on", b.dataset.mode === m); b.setAttribute("aria-selected", b.dataset.mode === m); });
  moveThumb();
  const [t, s, b] = copy[m];
  $("authTitle").textContent = t;
  $("authSub").textContent = s;
  $("submitBtn").textContent = b;
  $("password").autocomplete = m === "register" ? "new-password" : "current-password";
  $("err").textContent = "";
  (m === "register" ? $("name") : $("username")).focus();
}
document.querySelectorAll("#modeSeg button").forEach((b) => (b.onclick = () => setMode(b.dataset.mode)));
requestAnimationFrame(moveThumb);
addEventListener("resize", moveThumb);

$("pwToggle").onclick = () => {
  const p = $("password");
  p.type = p.type === "password" ? "text" : "password";
  $("pwToggle").setAttribute("aria-label", p.type === "password" ? "Show password" : "Hide password");
};

$("authForm").onsubmit = async (e) => {
  e.preventDefault();
  $("err").textContent = "";
  const body = { username: $("username").value.trim(), password: $("password").value };
  if (!body.username || !body.password) { $("err").textContent = "Enter a username and password."; return; }
  if (mode === "register") body.name = $("name").value.trim();
  $("submitBtn").disabled = true;
  try {
    const r = await fetch(`/api/auth/${mode}`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    const data = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(typeof data.detail === "string" ? data.detail : "Please check the form");
    document.body.classList.add("leaving");
    scene.setLevel(1, 1);
    setTimeout(() => (location.href = "/app"), 420);
  } catch (err) {
    $("err").textContent = err.message;
    $("authCard").animate([{ transform: "translateX(0)" }, { transform: "translateX(-8px)" }, { transform: "translateX(8px)" }, { transform: "translateX(0)" }],
                          { duration: 320, easing: "ease-out" });
  } finally {
    $("submitBtn").disabled = false;
  }
};

if (new URLSearchParams(location.search).has("new")) setMode("register");
$("username").focus();
