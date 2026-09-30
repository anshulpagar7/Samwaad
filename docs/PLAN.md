# Plan to the deadline (30 Sep 2026, 11:59 PM IST → submit by the afternoon)

## ✅ Done
- Live pipeline (VAD → Whisper → translation → store) with stage/audio/metrics events
- NPU path: onnxruntime-qnn 2.x plugin + 1.x support, AI Hub Whisper decoder (exact I/O contract, tested), OPUS-MT NPU translator + export tool, hybrid router with IndicTrans2
- One-click setup, `samwaad doctor`, auto CPU/NPU, `--demo` mode, PyInstaller + Inno Setup installer scripts
- UI: Liquid Glass + 3D orb, home dashboard, live view with pipeline visualiser, library, lecture + 3D flashcards/quiz, On-device AI page, settings with accessibility, command palette, onboarding
- Docs: README, NPU.md, ARCHITECTURE.md, SUBMISSION.md, architecture diagram, screenshots

## Today (29 Sep) — on any laptop
- [ ] `python -m samwaad --demo app` → click through everything once
- [ ] Get a free Qualcomm AI Hub token; run `python tools/export_opus_mt.py hi mr dra` (compiles on AI Hub's hosted X Elite — no Snapdragon needed)
- [ ] Record your own 3–5 min explanation of a CS topic → `samples/lecture.wav`
- [ ] Create the GitHub repo and push

## Snapdragon laptop session (as soon as you have it)
- [ ] `scripts\setup.bat` (ARM64 Python!) → `python -m samwaad doctor` all green
- [ ] Copy `models/opus_mt/` from the export step
- [ ] Live test: speak → captions + Hindi/Marathi; Task Manager NPU graph moves
- [ ] `python tools/benchmark.py models` and `python tools/benchmark.py pipeline samples/lecture.wav -o runtime.device=cpu` then `…device=npu`
- [ ] Record the demo video (script in SUBMISSION.md), Wi-Fi visibly off
- [ ] Optional: `scripts\build_installer.ps1` → attach Samwaad-Setup.exe to a GitHub release

## 30 Sep
- [ ] Update README benchmark table with your measured numbers
- [ ] Fill SUBMISSION.md TODO links, proofread, submit by ~3 PM
