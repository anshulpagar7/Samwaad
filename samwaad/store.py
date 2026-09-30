"""Lecture store — plain JSONL + Markdown on disk, one folder per lecture, nothing leaves the laptop."""
from __future__ import annotations

import json
import threading
import time
from dataclasses import asdict, dataclass, field, fields
from datetime import datetime
from pathlib import Path


@dataclass
class Line:
    idx: int
    start_s: float
    end_s: float
    text: str
    translation: str = ""
    target: str | None = None
    asr_ms: float = 0.0
    mt_ms: float = 0.0
    asr_backend: str = ""
    mt_engine: str = ""
    e2e_ms: float = 0.0       # speaker paused -> caption ready
    wall: float = field(default_factory=time.time)


_LINE_FIELDS = {f.name for f in fields(Line)}


class SessionStore:
    def __init__(self, root: str, title: str | None = None):
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        sid, n = stamp, 0
        while (Path(root) / sid).exists():  # two lectures in the same second
            n += 1
            sid = f"{stamp}-{n}"
        self.id = sid
        self.dir = Path(root) / sid
        self.dir.mkdir(parents=True, exist_ok=True)
        self.title = title or f"Lecture {datetime.now():%d %b %Y, %H:%M}"
        self.meta = {"id": self.id, "title": self.title, "created": time.time(), "starred": False}
        self.lines: list[Line] = []
        self._lock = threading.Lock()
        self.save_meta()

    def save_meta(self, **updates):
        self.meta.update(updates)
        self.title = self.meta["title"]
        (self.dir / "meta.json").write_text(json.dumps(self.meta, ensure_ascii=False), encoding="utf-8")

    def add(self, line: Line):
        with self._lock:
            self.lines.append(line)
            with open(self.dir / "transcript.jsonl", "a", encoding="utf-8") as f:
                f.write(json.dumps(asdict(line), ensure_ascii=False) + "\n")

    def text(self) -> str:
        return " ".join(l.text for l in self.lines if l.text)

    def export_markdown(self) -> Path:
        out = [f"# {self.title}\n"]
        for l in self.lines:
            ts = f"{int(l.start_s // 60):02d}:{int(l.start_s % 60):02d}"
            out.append(f"**[{ts}]** {l.text}")
            if l.translation:
                out.append(f"> {l.translation}")
            out.append("")
        p = self.dir / "transcript.md"
        p.write_text("\n".join(out), encoding="utf-8")
        return p

    def stats(self) -> dict:
        asr = [l.asr_ms for l in self.lines if l.asr_ms]
        mt = [l.mt_ms for l in self.lines if l.mt_ms]
        e2e = [l.e2e_ms for l in self.lines if l.e2e_ms]
        audio_s = sum(l.end_s - l.start_s for l in self.lines)
        avg = lambda xs: round(sum(xs) / len(xs), 1) if xs else 0.0
        return {
            "lines": len(self.lines),
            "words": sum(len(l.text.split()) for l in self.lines),
            "audio_s": round(audio_s, 1),
            "duration_s": round(self.lines[-1].end_s, 1) if self.lines else 0.0,
            "asr_ms_avg": avg(asr),
            "mt_ms_avg": avg(mt),
            "e2e_ms_avg": avg(e2e),
            # real-time factor: processing time / audio duration (lower is better; <1 = faster than realtime)
            "rtf": round((sum(asr) + sum(mt)) / 1000 / audio_s, 3) if audio_s else 0.0,
            "languages": sorted({l.target for l in self.lines if l.target}),
            "engines": sorted({e for l in self.lines for e in (l.asr_backend, l.mt_engine) if e}),
        }

    @staticmethod
    def load(folder: str | Path) -> "SessionStore":
        folder = Path(folder)
        s = SessionStore.__new__(SessionStore)
        meta = json.loads((folder / "meta.json").read_text(encoding="utf-8"))
        meta.setdefault("starred", False)
        meta.setdefault("created", (folder / "meta.json").stat().st_mtime)
        s.meta, s.id, s.title, s.dir = meta, meta["id"], meta["title"], folder
        s._lock = threading.Lock()
        s.lines = []
        tp = folder / "transcript.jsonl"
        if tp.exists():
            for raw in tp.read_text(encoding="utf-8").splitlines():
                if raw.strip():
                    d = json.loads(raw)
                    s.lines.append(Line(**{k: v for k, v in d.items() if k in _LINE_FIELDS}))
        return s
