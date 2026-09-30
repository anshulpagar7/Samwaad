"""Samwaad CLI.

  python -m samwaad app                         # start + open the app window (what the desktop shortcut runs)
  python -m samwaad serve                       # web app at http://127.0.0.1:8765 (no window)
  python -m samwaad doctor                      # is this PC ready? NPU, models, mic, LLM — with fixes
  python -m samwaad live                        # captions in the terminal (mic)
  python -m samwaad transcribe lecture.wav      # file -> transcript (+ stats), as fast as possible
  python -m samwaad studykit sessions/<user>/<id>   # build a study kit for a saved lecture
  python -m samwaad --demo app                  # try the full UI with a scripted lecture — no models needed
  python -m samwaad status                      # runtime / execution provider as JSON
  python -m samwaad devices                     # list audio input devices

Any config key can be overridden:  -o runtime.device=cpu -o asr.backend=faster-whisper
"""
from __future__ import annotations

import argparse
import json
import logging
import shutil
import socket
import subprocess
import sys
import threading
import time
import webbrowser


def _port_open(host: str, port: int) -> bool:
    try:
        socket.create_connection((host, port), timeout=0.3).close()
        return True
    except OSError:
        return False


def open_window(url: str):
    """Edge/Chrome app mode = a clean native-looking window with no tabs or address bar."""
    for exe in ("msedge", "microsoft-edge", "chrome", "google-chrome", "chromium"):
        path = shutil.which(exe)
        if path:
            subprocess.Popen([path, f"--app={url}", "--window-size=1440,900"])
            return
    if sys.platform == "win32":  # msedge is rarely on PATH on Windows, but the protocol handler is
        subprocess.Popen(["cmd", "/c", "start", "", "msedge", f"--app={url}"], shell=False)
        return
    webbrowser.open(url)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="samwaad", description="Samwaad — offline classroom companion")
    ap.add_argument("-c", "--config", default=None)
    ap.add_argument("-o", "--override", action="append", default=[], help="section.key=value")
    ap.add_argument("-v", "--verbose", action="store_true")
    ap.add_argument("--demo", action="store_true",
                    help="scripted demo lecture (real Hindi/Tamil/Marathi text) — try the whole UI without any models")
    sub = ap.add_subparsers(dest="cmd")
    sub.add_parser("app")
    sub.add_parser("serve")
    sub.add_parser("doctor")
    sub.add_parser("live")
    t = sub.add_parser("transcribe")
    t.add_argument("wav")
    t.add_argument("--realtime", action="store_true", help="replay at 1x speed like a live mic")
    k = sub.add_parser("studykit")
    k.add_argument("session_dir")
    sub.add_parser("status")
    sub.add_parser("devices")
    # Global flags work before or after the sub-command:  samwaad -o x=y serve  ==  samwaad serve -o x=y
    raw = list(sys.argv[1:] if argv is None else argv)
    hoisted, rest, i = [], [], 0
    while i < len(raw):
        a = raw[i]
        if a in ("-o", "--override", "-c", "--config") and i + 1 < len(raw):
            hoisted += [a, raw[i + 1]]
            i += 2
            continue
        (hoisted if a in ("-v", "--verbose", "--demo") or a.startswith(("--override=", "--config=")) else rest).append(a)
        i += 1
    args = ap.parse_args(hoisted + rest)

    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s", datefmt="%H:%M:%S")
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")  # Devanagari/Tamil in Windows terminals

    from .config import load_config

    if args.demo:
        args.override = ["asr.backend=script", "translate.backend=script", "vad.backend=energy",
                         "llm.backend=extractive"] + args.override
    cfg = load_config(args.config, args.override)
    cmd = args.cmd or "app"

    if cmd == "devices":
        from .audio import list_devices
        print(list_devices())
    elif cmd == "status":
        from .runtime import describe
        print(json.dumps(describe(cfg.get("runtime")), indent=2))
    elif cmd == "doctor":
        from .doctor import print_report
        sys.exit(print_report(cfg))
    elif cmd in ("serve", "app"):
        host, port = cfg["server"]["host"], cfg["server"]["port"]
        url = f"http://{host}:{port}"
        if _port_open(host, port):  # already running (e.g. double-clicked twice) -> just open a window
            print(f"Samwaad is already running at {url}")
            if cmd == "app":
                open_window(url)
            return
        import uvicorn

        from .server import create_app
        app = create_app(cfg)
        print(f"\n  Samwaad running →  {url}\n")
        if cmd == "app":
            def _open():
                for _ in range(100):
                    if _port_open(host, port):
                        open_window(url)
                        return
                    time.sleep(0.1)
            threading.Thread(target=_open, daemon=True).start()
        uvicorn.run(app, host=host, port=port, log_level="warning")
    elif cmd in ("live", "transcribe"):
        from .pipeline import Engine
        eng = Engine(cfg)

        def show(ev):
            if ev["type"] == "caption":
                l = ev["line"]
                print(f"[{l['start_s']:7.1f}s] {l['text']}   ({l['asr_ms']:.0f} ms, {l['asr_backend']})", flush=True)
            elif ev["type"] == "translation":
                print(f"           ↳ {ev['text']}   ({ev['mt_ms']:.0f} ms, {ev.get('engine', '')})", flush=True)
            elif ev["type"] == "stopped":
                print("\nstats:", json.dumps(ev["stats"], ensure_ascii=False))
            elif ev["type"] == "error":
                print("ERROR", ev, file=sys.stderr)

        eng.subscribe(show)
        if cmd == "live":
            eng.start("mic")
            print("Listening… Ctrl+C to stop.")
        else:
            eng.start("file", args.wav, realtime=args.realtime)
        try:
            while eng.running:
                eng.wait(0.5)
        except KeyboardInterrupt:
            eng.stop()
            eng.wait()
        print(f"Saved to {eng.session.dir}")
    elif cmd == "studykit":
        from .store import SessionStore
        from .studykit import StudyKit
        s = SessionStore.load(args.session_dir)
        kit = StudyKit(cfg.get("llm", {})).build(s.text())
        (s.dir / "studykit.json").write_text(json.dumps(kit, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(kit, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
