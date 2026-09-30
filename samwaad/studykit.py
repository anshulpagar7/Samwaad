"""Post-lecture study kit: summary, key points, flashcards, and ask-the-lecture Q&A.

LLM backends (all local):
  http       : any OpenAI-compatible local server — Ollama, llama.cpp server, LM Studio,
               or Qualcomm's on-device LLM served over HTTP. Zero extra Python deps.
  genie      : Qualcomm Genie SDK CLI (`genie-t2t-run`) with an AI Hub LLM bundle — runs on the NPU.
  extractive : no LLM at all; frequency-based summary + cloze flashcards. Always works,
               so the demo never dies even if the LLM isn't set up.
"""
from __future__ import annotations

import json
import logging
import re
import subprocess
import time
import urllib.request
from collections import Counter

log = logging.getLogger(__name__)

SYSTEM = ("You are a study assistant for university students. Use ONLY the lecture transcript. "
          "Be accurate and concise. If the transcript doesn't contain the answer, say so.")

KIT_PROMPT = """Lecture transcript:
\"\"\"{transcript}\"\"\"

Return ONLY valid JSON with this exact shape:
{{"summary": "5-7 sentence summary",
  "key_points": ["...", "..."],
  "flashcards": [{{"q": "question", "a": "answer"}}],
  "terms": [{{"term": "...", "meaning": "..."}}]}}
Give 5-8 key points, 6-10 flashcards and up to 8 terms."""

QA_PROMPT = """Lecture transcript:
\"\"\"{transcript}\"\"\"

Question: {question}
Answer in 2-4 sentences using only the transcript."""

MAX_CHARS = 12000  # ~3k tokens; keeps a 3B model inside its context on-device


def _clip(t: str) -> str:
    if len(t) <= MAX_CHARS:
        return t
    half = MAX_CHARS // 2  # keep the start and the end of long lectures
    return t[:half] + "\n...\n" + t[-half:]


# ---------------------------------------------------------------- backends
class HttpLLM:
    name = "http"

    def __init__(self, url, model, max_tokens=900, timeout_s=180, **_):
        self.url, self.model, self.max_tokens, self.timeout = url, model, max_tokens, timeout_s

    def chat(self, prompt: str) -> str:
        body = json.dumps({
            "model": self.model, "temperature": 0.2, "max_tokens": self.max_tokens,
            "messages": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": prompt}],
        }).encode()
        req = urllib.request.Request(self.url, body, {"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=self.timeout) as r:
            return json.loads(r.read())["choices"][0]["message"]["content"]


class GenieLLM:
    """Qualcomm Genie (AI Hub LLM bundle). Llama 3 chat template applied here."""
    name = "genie"

    def __init__(self, genie_config, timeout_s=180, **_):
        self.config, self.timeout = genie_config, timeout_s

    def chat(self, prompt: str) -> str:
        full = ("<|begin_of_text|><|start_header_id|>system<|end_header_id|>\n\n" + SYSTEM +
                "<|eot_id|><|start_header_id|>user<|end_header_id|>\n\n" + prompt +
                "<|eot_id|><|start_header_id|>assistant<|end_header_id|>\n\n")
        out = subprocess.run(["genie-t2t-run", "-c", self.config, "-p", full],
                             capture_output=True, text=True, timeout=self.timeout, check=True).stdout
        m = re.search(r"\[BEGIN\]:(.*?)\[END\]", out, re.S)
        return (m.group(1) if m else out).strip()


# ---------------------------------------------------------------- extractive fallback
_STOP = set("""a an the and or but if of to in on at for with by from is are was were be been being this that
these those it its as so we you they he she i our your their there here what which who whom when where why how
can could will would should may might must do does did not no yes just also very really then than now okay ok
um uh like actually basically right going get got have has had one two let lets say see know think""".split())


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if len(s.split()) >= 5]


def extractive_kit(text: str) -> dict:
    sents = _sentences(text)
    words = [w for w in re.findall(r"[a-zA-Z][a-zA-Z\-]{2,}", text.lower()) if w not in _STOP]
    freq = Counter(words)
    if not sents or not freq:
        return {"summary": text[:500], "key_points": [], "flashcards": [], "terms": []}
    top = max(freq.values())
    score = lambda s: sum(freq.get(w, 0) / top for w in re.findall(r"[a-z\-]+", s.lower())) / (len(s.split()) ** 0.5)
    ranked = sorted(range(len(sents)), key=lambda i: score(sents[i]), reverse=True)
    summary_idx = sorted(ranked[:6])
    key_idx = ranked[:8]
    keywords = [w for w, _ in freq.most_common(20)]
    cards = []
    for i in key_idx:
        s = sents[i]
        kw = next((k for k in keywords if re.search(rf"\b{re.escape(k)}\b", s, re.I)), None)
        if kw:
            q = re.sub(rf"\b{re.escape(kw)}\b", "_____", s, count=1, flags=re.I)
            cards.append({"q": f"Fill in the blank: {q}", "a": kw})
    return {
        "summary": " ".join(sents[i] for i in summary_idx),
        "key_points": [sents[i] for i in key_idx],
        "flashcards": cards[:8],
        "terms": [{"term": k, "meaning": ""} for k in keywords[:8]],
    }


def _parse_json(raw: str) -> dict:
    raw = raw.strip()
    raw = re.sub(r"^```(?:json)?|```$", "", raw, flags=re.M).strip()
    start, end = raw.find("{"), raw.rfind("}")
    return json.loads(raw[start:end + 1])


# ---------------------------------------------------------------- public API
class StudyKit:
    def __init__(self, llm_cfg: dict):
        backend = llm_cfg.get("backend", "extractive")
        self.llm = {"http": HttpLLM, "genie": GenieLLM}.get(backend)
        self.llm = self.llm(**llm_cfg) if self.llm else None

    def build(self, transcript: str) -> dict:
        t0 = time.perf_counter()
        kit, engine = None, "extractive"
        if self.llm and transcript.strip():
            try:
                kit = _parse_json(self.llm.chat(KIT_PROMPT.format(transcript=_clip(transcript))))
                engine = self.llm.name
            except Exception as e:
                log.warning("LLM study kit failed (%s); using extractive fallback.", e)
        kit = kit or extractive_kit(transcript)
        kit.setdefault("key_points", []), kit.setdefault("flashcards", []), kit.setdefault("terms", [])
        kit["engine"] = engine
        kit["latency_s"] = round(time.perf_counter() - t0, 2)
        return kit

    def ask(self, transcript: str, question: str) -> dict:
        t0 = time.perf_counter()
        if self.llm:
            try:
                ans = self.llm.chat(QA_PROMPT.format(transcript=_clip(transcript), question=question))
                return {"answer": ans, "engine": self.llm.name, "latency_s": round(time.perf_counter() - t0, 2)}
            except Exception as e:
                log.warning("LLM Q&A failed (%s); using retrieval fallback.", e)
        # Fallback: return the transcript sentences that overlap most with the question.
        q = {w for w in re.findall(r"[a-z]{3,}", question.lower()) if w not in _STOP}
        sents = _sentences(transcript)
        best = sorted(sents, key=lambda s: len(q & set(re.findall(r"[a-z]{3,}", s.lower()))), reverse=True)[:3]
        ans = " ".join(best) if best and q else "I couldn't find that in this lecture."
        return {"answer": ans, "engine": "retrieval", "latency_s": round(time.perf_counter() - t0, 2)}
