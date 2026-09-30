"""Local web app server (127.0.0.1 only). FastAPI + WebSocket push of live captions.

Pure-Python deps, so it installs cleanly on Windows on ARM64. The launcher opens it in Edge
app mode for a native-feeling window:  msedge --app=http://127.0.0.1:8765
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import shutil
import socket
import time
from collections import Counter
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request, Response, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .auth import AuthError, AuthStore
from .config import ROOT, resource
from .pipeline import Engine
from .runtime import describe
from .store import SessionStore
from .studykit import StudyKit
from .translate import LANGUAGES, NATIVE

log = logging.getLogger(__name__)
WEB = Path(__file__).parent / "web"
COOKIE = "samwaad_session"
SID_RE = re.compile(r"[0-9]{8}-[0-9]{6}(-\d+)?")

# user-tunable settings and their allowed values
PREFS = {
    "target": lambda v: v is None or v in LANGUAGES,
    "prefer": lambda v: v in ("npu", "quality"),
    "caption_scale": lambda v: isinstance(v, (int, float)) and 0.8 <= v <= 2.2,
    "contrast": lambda v: isinstance(v, bool),
    "reduce_motion": lambda v: isinstance(v, bool),
    "readable_font": lambda v: isinstance(v, bool),
    "mic": lambda v: v is None or isinstance(v, (int, str)),
    "onboarded": lambda v: isinstance(v, bool),
}


class StartReq(BaseModel):
    source: str = "mic"
    wav: str | None = None
    title: str | None = None


class TargetReq(BaseModel):
    target: str | None = None


class AskReq(BaseModel):
    question: str


class PatchReq(BaseModel):
    title: str | None = None
    starred: bool | None = None


class RegisterReq(BaseModel):
    username: str
    password: str
    name: str = ""


class LoginReq(BaseModel):
    username: str
    password: str


def is_online(timeout: float = 0.35) -> bool:
    try:
        socket.create_connection(("1.1.1.1", 53), timeout=timeout).close()
        return True
    except OSError:
        return False


def _snippet(text: str, q: str, width: int = 90) -> str:
    if not q:
        return text[:width * 2]
    i = text.lower().find(q.lower())
    if i < 0:
        return text[:width * 2]
    a, b = max(0, i - width), min(len(text), i + len(q) + width)
    return ("…" if a else "") + text[a:b] + ("…" if b < len(text) else "")


def create_app(cfg: dict, engine: Engine | None = None) -> FastAPI:
    loop_holder: dict = {}

    @asynccontextmanager
    async def lifespan(_app):
        loop_holder["loop"] = asyncio.get_running_loop()
        yield
        engine.stop()

    app = FastAPI(title="Samwaad", lifespan=lifespan, docs_url=None, redoc_url=None)
    engine = engine or Engine(cfg)
    kit = StudyKit(cfg.get("llm", {}))
    root = Path(cfg["store"]["dir"])
    auth = AuthStore(cfg.get("auth", {}).get("dir") or (root.parent / "data"))
    clients: dict[asyncio.Queue, str] = {}  # queue -> username
    net = {"t": 0.0, "online": False}

    def on_event(ev: dict):  # called from worker threads
        loop = loop_holder.get("loop")
        if not loop:
            return
        msg = json.dumps(ev, ensure_ascii=False, default=str)
        for q, user in list(clients.items()):
            if user == engine.owner:  # live captions only go to the account that started them
                loop.call_soon_threadsafe(q.put_nowait, msg)

    engine.subscribe(on_event)

    def online() -> bool:  # cached — the status poll must never stall on a dead network
        if time.time() - net["t"] > 10:
            net.update(t=time.time(), online=is_online())
        return net["online"]

    # ---------------------------------------------------------------- auth plumbing
    def current_user(request: Request) -> str:
        user = auth.user_for(request.cookies.get(COOKIE))
        if not user:
            raise HTTPException(401, "Please sign in")
        return user

    def user_dir(user: str) -> Path:
        return root / user

    def load(user: str, sid: str) -> SessionStore:
        folder = user_dir(user) / sid
        if not SID_RE.fullmatch(sid) or not (folder / "meta.json").exists():
            raise HTTPException(404, "No such lecture")
        return SessionStore.load(folder)

    def all_sessions(user: str) -> list[SessionStore]:
        d = user_dir(user)
        if not d.exists():
            return []
        return [SessionStore.load(f) for f in sorted(d.iterdir(), reverse=True)
                if SID_RE.fullmatch(f.name) and (f / "meta.json").exists()]

    def set_cookie(resp: Response, token: str):
        resp.set_cookie(COOKIE, token, httponly=True, samesite="strict", max_age=30 * 24 * 3600)

    def apply_prefs(user: str):
        prefs = auth.public(user)["prefs"]
        if prefs.get("prefer"):
            engine.set_prefer(prefs["prefer"])
        if "mic" in prefs:
            engine.cfg["audio"]["device"] = prefs["mic"]
        if "target" in prefs and (prefs["target"] is None or prefs["target"] in LANGUAGES):
            engine.set_target(prefs["target"])

    # ---------------------------------------------------------------- pages
    @app.get("/")
    def index(request: Request):
        ok = auth.user_for(request.cookies.get(COOKIE))
        return RedirectResponse("/app" if ok else "/login")

    @app.get("/login")
    def login_page():
        return FileResponse(WEB / "login.html")

    @app.get("/app")
    def app_page(request: Request):
        if not auth.user_for(request.cookies.get(COOKIE)):
            return RedirectResponse("/login")
        return FileResponse(WEB / "app.html")

    app.mount("/static", StaticFiles(directory=WEB), name="static")

    # ---------------------------------------------------------------- auth API
    @app.post("/api/auth/register")
    def register(req: RegisterReq, resp: Response):
        try:
            user = auth.register(req.username, req.password, req.name)
        except AuthError as e:
            raise HTTPException(400, str(e))
        set_cookie(resp, auth.create_session(user["username"]))
        return user

    @app.post("/api/auth/login")
    def login(req: LoginReq, resp: Response):
        try:
            user = auth.verify(req.username, req.password)
        except AuthError as e:
            raise HTTPException(401, str(e))
        set_cookie(resp, auth.create_session(user["username"]))
        return user

    @app.post("/api/auth/logout")
    def logout(request: Request, resp: Response):
        auth.revoke(request.cookies.get(COOKIE))
        resp.delete_cookie(COOKIE)
        return {"ok": True}

    @app.get("/api/auth/me")
    def me(user: str = Depends(current_user)):
        return auth.public(user)

    # ---------------------------------------------------------------- settings
    @app.get("/api/settings")
    def get_settings(user: str = Depends(current_user)):
        return auth.public(user)["prefs"]

    @app.put("/api/settings")
    def put_settings(body: dict, user: str = Depends(current_user)):
        for k, v in body.items():
            if k not in PREFS or not PREFS[k](v):
                raise HTTPException(400, f"Invalid setting {k}={v!r}")
        for k, v in body.items():
            auth.set_pref(user, k, v)
        if not engine.running:
            apply_prefs(user)
        return auth.public(user)["prefs"]

    @app.get("/api/devices")
    def devices(user: str = Depends(current_user)):
        try:
            import sounddevice as sd
            default_in = sd.default.device[0] if sd.default.device else None
            return [{"id": i, "name": d["name"], "default": i == default_in}
                    for i, d in enumerate(sd.query_devices()) if d["max_input_channels"] > 0]
        except Exception:
            return []

    # ---------------------------------------------------------------- live
    @app.get("/api/status")
    def status(user: str = Depends(current_user)):
        mine = engine.owner == user
        return {
            "running": engine.running and mine,
            "busy": engine.running and not mine,
            "session": engine.session.id if (engine.session and mine) else None,
            "started_at": engine.started_at if mine else None,
            "runtime": {k: v for k, v in engine.runtime.items() if k != "sessions"},
            "engines": engine.engines(),
            "asr": getattr(engine.asr, "name", "?"),
            "translator": getattr(engine.translator, "name", "?"),
            "llm": kit.llm.name if kit.llm else "extractive",
            "target": engine.target,
            "languages": LANGUAGES,
            "native": NATIVE,
            "online": online(),
        }

    @app.post("/api/start")
    def start(req: StartReq, user: str = Depends(current_user)):
        if engine.running:
            raise HTTPException(409, "A lecture is already being captioned")
        if getattr(engine.asr, "name", "") == "missing":
            raise HTTPException(400, engine.asr.reason)
        if req.source == "file":
            wav = Path(req.wav or "")
            wav = wav if wav.is_absolute() else resource(wav)
            if not wav.exists():
                raise HTTPException(400, f"Recording not found: {req.wav}")
            req.wav = str(wav)
        apply_prefs(user)
        try:
            s = engine.start(req.source, req.wav, req.title, user=user)
        except Exception as e:
            raise HTTPException(500, f"Couldn't start audio: {e}")
        return {"session": s.id, "title": s.title}

    @app.post("/api/stop")
    def stop(user: str = Depends(current_user)):
        if engine.owner == user:
            engine.stop()
        return {"ok": True}

    @app.post("/api/target")
    def target(req: TargetReq, user: str = Depends(current_user)):
        if req.target and req.target not in LANGUAGES:
            raise HTTPException(400, "Unknown language")
        engine.set_target(req.target)
        auth.set_pref(user, "target", req.target)
        return {"target": engine.target}

    @app.get("/api/metrics")
    def metrics(user: str = Depends(current_user)):
        return engine.metrics.snapshot()

    # ---------------------------------------------------------------- performance + system
    @app.get("/api/performance")
    def performance(user: str = Depends(current_user)):
        def read_json(p):
            try:
                return json.loads(resource(p).read_text(encoding="utf-8"))
            except (FileNotFoundError, json.JSONDecodeError):
                return None
        return {
            "runtime": describe(cfg.get("runtime")),
            "engines": engine.engines(),
            "published": read_json("benchmarks/aihub_published.json"),
            "local": read_json("benchmarks/local_results.json") or [],
            "live": engine.metrics.snapshot(),
        }

    @app.get("/api/doctor")
    async def doctor(user: str = Depends(current_user)):
        from .doctor import run_checks
        return await asyncio.to_thread(run_checks, cfg)

    # ---------------------------------------------------------------- library
    @app.get("/api/stats")
    def stats(user: str = Depends(current_user)):
        ss = all_sessions(user)
        today = datetime.now().date()
        days = [(today - timedelta(days=i)) for i in range(13, -1, -1)]
        per_day = Counter()
        langs, cards, kits = Counter(), 0, 0
        for s in ss:
            st = s.stats()
            per_day[datetime.fromtimestamp(s.meta.get("created", 0)).date()] += st["audio_s"] / 60
            for l in st["languages"]:
                langs[l] += 1
            kp = s.dir / "studykit.json"
            if kp.exists():
                kits += 1
                try:
                    cards += len(json.loads(kp.read_text(encoding="utf-8")).get("flashcards", []))
                except json.JSONDecodeError:
                    pass
        streak = 0
        for d in reversed(days):
            if per_day.get(d):
                streak += 1
            elif d != today:
                break
        return {
            "lectures": len(ss),
            "minutes": round(sum(s.stats()["audio_s"] for s in ss) / 60, 1),
            "words": sum(s.stats()["words"] for s in ss),
            "flashcards": cards,
            "study_kits": kits,
            "languages": [{"code": k, "name": LANGUAGES.get(k, k), "count": v} for k, v in langs.most_common()],
            "days": [{"date": d.isoformat(), "label": d.strftime("%a"), "minutes": round(per_day.get(d, 0), 1)} for d in days],
            "streak": streak,
        }

    @app.get("/api/sessions")
    def sessions(q: str = "", starred: bool = False, user: str = Depends(current_user)):
        out = []
        for s in all_sessions(user):
            text = s.text()
            if q and q.lower() not in (s.title + " " + text).lower():
                continue
            if starred and not s.meta.get("starred"):
                continue
            out.append({"id": s.id, "title": s.title, "created": s.meta.get("created"), "starred": s.meta.get("starred", False),
                        **s.stats(), "snippet": _snippet(text, q), "has_kit": (s.dir / "studykit.json").exists(),
                        "live": engine.running and engine.session is not None and engine.session.id == s.id})
        return out

    @app.get("/api/sessions/{sid}")
    def session(sid: str, user: str = Depends(current_user)):
        s = load(user, sid)
        kit_path = s.dir / "studykit.json"
        return {"id": s.id, "title": s.title, "created": s.meta.get("created"), "starred": s.meta.get("starred", False),
                "stats": s.stats(), "lines": [l.__dict__ for l in s.lines],
                "studykit": json.loads(kit_path.read_text(encoding="utf-8")) if kit_path.exists() else None}

    @app.patch("/api/sessions/{sid}")
    def patch(sid: str, req: PatchReq, user: str = Depends(current_user)):
        s = load(user, sid)
        upd = {}
        if req.title is not None:
            upd["title"] = req.title.strip()[:120] or s.title
        if req.starred is not None:
            upd["starred"] = req.starred
        s.save_meta(**upd)
        return {"id": sid, "title": s.title, "starred": s.meta["starred"]}

    @app.delete("/api/sessions/{sid}")
    def delete(sid: str, user: str = Depends(current_user)):
        s = load(user, sid)
        if engine.running and engine.session and engine.session.id == sid:
            raise HTTPException(409, "Stop the lecture before deleting it")
        shutil.rmtree(s.dir)
        return {"ok": True}

    @app.get("/api/sessions/{sid}/export")
    def export(sid: str, user: str = Depends(current_user)):
        s = load(user, sid)
        md = s.export_markdown().read_text(encoding="utf-8")
        kp = s.dir / "studykit.json"
        if kp.exists():
            k = json.loads(kp.read_text(encoding="utf-8"))
            md += "\n---\n\n## Summary\n\n" + k.get("summary", "") + "\n\n## Key points\n\n"
            md += "\n".join(f"- {p}" for p in k.get("key_points", []))
            md += "\n\n## Flashcards\n\n" + "\n".join(f"- **Q:** {c['q']}  \n  **A:** {c['a']}"
                                                      for c in k.get("flashcards", []))
            if k.get("terms"):
                md += "\n\n## Terms\n\n" + "\n".join(f"- **{t['term']}**" + (f": {t['meaning']}" if t.get("meaning") else "")
                                                     for t in k["terms"])
        name = re.sub(r"[^A-Za-z0-9_-]+", "_", s.title).strip("_") or sid
        return PlainTextResponse(md, media_type="text/markdown",
                                 headers={"Content-Disposition": f'attachment; filename="{name}.md"'})

    @app.post("/api/sessions/{sid}/studykit")
    async def studykit(sid: str, user: str = Depends(current_user)):
        s = load(user, sid)
        result = await asyncio.to_thread(kit.build, s.text())
        (s.dir / "studykit.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        return result

    @app.post("/api/sessions/{sid}/ask")
    async def ask(sid: str, req: AskReq, user: str = Depends(current_user)):
        s = load(user, sid)
        return await asyncio.to_thread(kit.ask, s.text(), req.question)

    # ---------------------------------------------------------------- websocket
    @app.websocket("/ws")
    async def ws(sock: WebSocket):
        user = auth.user_for(sock.cookies.get(COOKIE))
        if not user:
            await sock.close(code=4401)
            return
        await sock.accept()
        q: asyncio.Queue = asyncio.Queue()
        clients[q] = user
        try:
            while True:
                await sock.send_text(await q.get())
        except (WebSocketDisconnect, RuntimeError):
            pass
        finally:
            clients.pop(q, None)

    app.state.engine = engine
    app.state.auth = auth
    return app
