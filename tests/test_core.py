"""Model-free tests: run anywhere in seconds (`pytest -q`)."""
import json
import sys
import time
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from samwaad.asr import log_mel
from samwaad.audio import read_wav, write_wav
from samwaad.config import apply_overrides, load_config
from samwaad.runtime import CPU, QNN, describe, make_session, wants_npu
from samwaad.store import Line, SessionStore
from samwaad.studykit import StudyKit, _parse_json, extractive_kit
from samwaad.vad import EnergyVAD, Segmenter

SR = 16000

LECTURE = (
    "Today we study the Raft consensus algorithm used in distributed systems. "
    "Raft elects a leader that manages log replication across the cluster. "
    "Each follower accepts log entries from the leader and replies with an acknowledgement. "
    "If the leader crashes, followers start an election after a randomized timeout. "
    "A candidate needs votes from a majority of servers to become the new leader. "
    "Safety in Raft means committed log entries are never lost or overwritten. "
    "Compared with Paxos, Raft was designed to be understandable for students and engineers."
)


def fake_lecture(n_utts=3, speech_s=1.2, gap_s=0.9):
    """Voiced-ish bursts (harmonics + noise) separated by near-silence."""
    rng = np.random.default_rng(0)
    parts = [rng.normal(0, 0.002, int(0.5 * SR))]
    for i in range(n_utts):
        t = np.arange(int(speech_s * SR)) / SR
        f0 = 140 + 20 * i
        burst = sum(np.sin(2 * np.pi * f0 * k * t) / k for k in range(1, 6)) * 0.2
        burst += rng.normal(0, 0.02, len(t))
        parts += [burst, rng.normal(0, 0.002, int(gap_s * SR))]
    return np.concatenate(parts).astype(np.float32)


def test_segmenter_splits_utterances():
    audio = fake_lecture(3)
    seg = Segmenter(EnergyVAD(SR), SR, threshold=0.5, min_speech_ms=200, min_silence_ms=400)
    out = []
    for i in range(0, len(audio), 700):  # odd block size on purpose
        out += seg.feed(audio[i:i + 700])
    last = seg.flush()
    out += [last] if last else []
    assert len(out) == 3
    for s in out:
        assert 1.0 < (s.end_s - s.start_s) < 1.8


def test_segmenter_forces_cut_on_long_speech():
    audio = fake_lecture(1, speech_s=5.0)
    seg = Segmenter(EnergyVAD(SR), SR, min_speech_ms=200, min_silence_ms=400, max_segment_s=2)
    out = seg.feed(audio)
    out += [x for x in [seg.flush()] if x]
    assert len(out) >= 2
    assert all(s.end_s - s.start_s <= 2.05 for s in out)


def test_log_mel_shape_and_range():
    m = log_mel(fake_lecture(1))
    assert m.shape == (1, 80, 3000)
    assert m.dtype == np.float32
    assert -1.6 < m.min() and m.max() < 3.0


def test_wav_roundtrip(tmp_path):
    a = fake_lecture(1)
    p = tmp_path / "x.wav"
    write_wav(str(p), a)
    b = read_wav(str(p))
    assert len(b) == len(a) and np.abs(a - b).max() < 1e-3


def test_config_overrides():
    cfg = apply_overrides({"runtime": {"device": "cpu"}}, ["runtime.device=npu", "vad.threshold=0.3", "x.y=true"])
    assert cfg["runtime"]["device"] == "npu" and cfg["vad"]["threshold"] == 0.3 and cfg["x"]["y"] is True
    assert load_config()["server"]["port"] == 8765


def test_runtime_device_selection():
    d = describe({"device": "auto"})
    assert d["execution_provider"] in (CPU, QNN) and "onnxruntime" in d
    assert wants_npu({"device": "cpu"}) is False
    if QNN not in d["available"]:  # dev machine: npu request degrades gracefully, or fails loudly if asked to
        assert wants_npu({"device": "npu", "fallback_to_cpu": True}) is False
        with pytest.raises(RuntimeError):
            wants_npu({"device": "npu", "fallback_to_cpu": False})


def test_spectrum_bands_and_metrics():
    from samwaad.metrics import Metrics
    from samwaad.pipeline import spectrum_bands

    t = np.arange(512) / SR
    bands = spectrum_bands((0.5 * np.sin(2 * np.pi * 1000 * t)).astype(np.float32))
    assert len(bands) == 16 and max(bands) == bands[int(np.argmax(bands))] and 0 <= min(bands) and max(bands) <= 1
    assert np.argmax(bands) in range(6, 12)          # 1 kHz lands in the middle bands
    assert spectrum_bands(np.zeros(512, np.float32)) == [0.0] * 16
    m = Metrics()
    m.add_sentence(4.0, 150, 45, 100, 25, 80, 260)
    m.add_sentence(6.0, 170, 46, 120, 30, 90, 280)
    m.sample()
    snap = m.snapshot()
    assert snap["stages"]["asr_ms"]["avg"] == 160 and snap["stages"]["tok_ms"]["n"] == 2
    assert snap["rtf"] == pytest.approx((150 + 80 + 170 + 90) / 1000 / 10, abs=1e-3)


def test_store_roundtrip(tmp_path):
    s = SessionStore(str(tmp_path), "Raft 101")
    s.add(Line(0, 0.0, 2.0, "Hello class.", "नमस्ते कक्षा।", "hin_Deva", asr_ms=100, mt_ms=50))
    s.add(Line(1, 3.0, 5.0, "Today, Raft.", asr_ms=300))
    s.export_markdown()
    r = SessionStore.load(s.dir)
    assert r.title == "Raft 101" and len(r.lines) == 2 and r.lines[0].translation == "नमस्ते कक्षा।"
    st = r.stats()
    assert st["asr_ms_avg"] == 200 and st["audio_s"] == 4.0 and st["rtf"] == pytest.approx(0.45 / 4, abs=1e-3)
    assert st["words"] == 4 and st["languages"] == ["hin_Deva"] and r.meta["starred"] is False
    assert "नमस्ते" in (s.dir / "transcript.md").read_text(encoding="utf-8")


def test_extractive_kit_and_fallback_qa():
    kit = extractive_kit(LECTURE)
    assert kit["summary"] and len(kit["key_points"]) >= 5 and kit["flashcards"]
    assert all("_____" in c["q"] for c in kit["flashcards"])
    sk = StudyKit({"backend": "extractive"})
    assert sk.build(LECTURE)["engine"] == "extractive"
    ans = sk.ask(LECTURE, "What happens when the leader crashes?")
    assert "election" in ans["answer"]


def test_llm_json_parsing_tolerates_fences():
    raw = "Sure!\n```json\n{\"summary\": \"s\", \"key_points\": [\"a\"]}\n```"
    assert _parse_json(raw)["key_points"] == ["a"]


def test_http_llm_failure_falls_back(monkeypatch):
    sk = StudyKit({"backend": "http", "url": "http://127.0.0.1:9/v1/chat/completions", "model": "x", "timeout_s": 1})
    assert sk.build(LECTURE)["engine"] == "extractive"
    assert sk.ask(LECTURE, "What is Raft?")["engine"] == "retrieval"


# ------------------------------------------------------------------ end-to-end (mock models)
@pytest.fixture
def mock_cfg(tmp_path):
    return load_config(overrides=[
        "asr.backend=mock", "translate.backend=mock", "vad.backend=energy", "llm.backend=extractive",
        f"store.dir={tmp_path / 'sessions'}", f"auth.dir={tmp_path / 'data'}", "vad.min_silence_ms=400",
    ])


@pytest.fixture
def lecture_wav(tmp_path):
    p = tmp_path / "lecture.wav"
    write_wav(str(p), fake_lecture(4))
    return str(p)


def test_pipeline_end_to_end(mock_cfg, lecture_wav):
    from samwaad.pipeline import Engine

    eng = Engine(mock_cfg)
    events = []
    eng.subscribe(events.append)
    eng.start("file", lecture_wav, realtime=False)
    eng.wait(10)
    kinds = [e["type"] for e in events]
    assert kinds[0] == "started" and kinds[-1] == "stopped"
    assert kinds.count("caption") == 4 and kinds.count("translation") == 4
    stages = [(e["stage"], e["state"]) for e in events if e["type"] == "stage"]
    assert stages.count(("asr", "done")) == 4 and stages.count(("mt", "done")) == 4 and ("vad", "done") in stages
    lv = next(e for e in events if e["type"] == "level")
    assert len(lv["bands"]) == 16
    stop = events[-1]
    assert stop["stats"]["lines"] == 4 and stop["metrics"]["stages"]["asr_ms"]["n"] == 4
    assert all(l.e2e_ms >= 0 and l.mt_engine == "mock:cpu" for l in eng.session.lines)
    assert (Path(eng.session.dir) / "transcript.md").exists()


def test_auth_store(tmp_path):
    from samwaad.auth import AuthError, AuthStore

    a = AuthStore(tmp_path)
    a.register("Anshul", "secret123", "Anshul P")
    with pytest.raises(AuthError):
        a.register("anshul", "another1")
    with pytest.raises(AuthError):
        a.register("x", "secret123")
    assert a.verify("ANSHUL", "secret123")["name"] == "Anshul P"
    with pytest.raises(AuthError):
        a.verify("anshul", "wrong")
    tok = a.create_session("anshul")
    assert AuthStore(tmp_path).user_for(tok) == "anshul"  # survives restart
    assert "secret123" not in (tmp_path / "users.json").read_text()
    a.revoke(tok)
    assert a.user_for(tok) is None


def test_server_flow(mock_cfg, lecture_wav):
    from fastapi.testclient import TestClient

    from samwaad.server import create_app

    app = create_app(mock_cfg)
    with TestClient(app) as c:
        assert c.get("/api/status").status_code == 401
        assert c.get("/", follow_redirects=False).headers["location"] == "/login"
        assert c.get("/login").status_code == 200
        assert c.post("/api/auth/register", json={"username": "anshul", "password": "pw1234", "name": "Anshul"}).status_code == 200
        assert c.get("/", follow_redirects=False).headers["location"] == "/app"
        assert c.get("/app").status_code == 200
        st = c.get("/api/status").json()
        assert st["asr"] == "mock" and "hin_Deva" in st["languages"]
        assert c.post("/api/target", json={"target": "tam_Taml"}).json()["target"] == "tam_Taml"
        assert c.post("/api/target", json={"target": "xx"}).status_code == 400
        with c.websocket_connect("/ws") as ws:
            sid = c.post("/api/start", json={"source": "file", "wav": lecture_wav, "title": "Raft lecture"}).json()["session"]
            seen = []
            while "stopped" not in seen:
                ev = json.loads(ws.receive_text())
                seen.append(ev["type"])
                if ev["type"] == "translation":
                    assert ev["text"].startswith("[tam_Taml]")
        assert seen.count("caption") == 4 and "level" in seen
        lib = c.get("/api/sessions").json()
        assert lib[0]["id"] == sid and lib[0]["lines"] == 4 and lib[0]["languages"] == ["tam_Taml"]
        assert c.get("/api/sessions?q=sentence 3").json()[0]["snippet"].lower().find("sentence 3") >= 0
        assert c.get("/api/sessions?q=zebra").json() == []
        assert c.patch(f"/api/sessions/{sid}", json={"title": "Raft, day 1"}).json()["title"] == "Raft, day 1"
        assert c.patch(f"/api/sessions/{sid}", json={"starred": True}).json()["starred"] is True
        assert [s["id"] for s in c.get("/api/sessions?starred=true").json()] == [sid]
        stats = c.get("/api/stats").json()
        assert stats["lectures"] == 1 and stats["languages"][0]["code"] == "tam_Taml" and len(stats["days"]) == 14
        assert stats["streak"] == 1
        # settings: validated, persisted, applied
        assert c.put("/api/settings", json={"caption_scale": 1.4, "contrast": True, "prefer": "quality"}).status_code == 200
        assert c.put("/api/settings", json={"caption_scale": 9}).status_code == 400
        assert c.put("/api/settings", json={"evil": 1}).status_code == 400
        assert c.get("/api/settings").json()["caption_scale"] == 1.4
        perf = c.get("/api/performance").json()
        assert perf["published"]["models"] and perf["runtime"]["execution_provider"] and "live" in perf
        assert c.get("/api/metrics").json()["stages"]["asr_ms"]["n"] == 4
        doc = c.get("/api/doctor").json()
        assert {d["name"] for d in doc} >= {"Snapdragon NPU (QNN)", "Speech recognition", "Translation", "Storage"}
        assert isinstance(c.get("/api/devices").json(), list)
        kit = c.post(f"/api/sessions/{sid}/studykit").json()
        assert kit["engine"] == "extractive"
        assert c.get(f"/api/sessions/{sid}").json()["studykit"] is not None
        exp = c.get(f"/api/sessions/{sid}/export")
        assert exp.status_code == 200 and "## Summary" in exp.text and "Raft_day_1" in exp.headers["content-disposition"]
        assert c.get("/api/sessions/..%2F..%2Fetc").status_code == 404

        # A second account can't see or touch the first account's notes.
        c.post("/api/auth/logout")
        assert c.get("/api/sessions").status_code == 401
        c.post("/api/auth/register", json={"username": "priya", "password": "pw5678"})
        assert c.get("/api/sessions").json() == []
        assert c.get(f"/api/sessions/{sid}").status_code == 404
        assert c.delete(f"/api/sessions/{sid}").status_code == 404

        c.post("/api/auth/logout")
        assert c.post("/api/auth/login", json={"username": "anshul", "password": "nope"}).status_code == 401
        assert c.post("/api/auth/login", json={"username": "anshul", "password": "pw1234"}).status_code == 200
        assert c.delete(f"/api/sessions/{sid}").json()["ok"]
        assert c.get("/api/sessions").json() == []


def test_cli_flags_work_after_subcommand(capsys):
    from samwaad.__main__ import main

    main(["status", "-o", "runtime.device=cpu", "--demo"])
    out = json.loads(capsys.readouterr().out)
    assert out["execution_provider"] == CPU and out["on_npu"] is False


def test_demo_script_translations_are_honest():
    from samwaad.translate import build_translator

    t = build_translator({"backend": "script", "target": "mar_Deva"})
    line = "Every server starts as a follower and waits to hear from a leader."
    assert t.translate(line, "mar_Deva")[0].startswith("प्रत्येक सर्व्हर")
    assert t.translate(line, "tam_Taml")[0]
    assert "needs the real models" in t.translate(line, "ben_Beng")[0]   # never shows a different language
