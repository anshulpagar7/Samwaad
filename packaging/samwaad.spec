# PyInstaller spec — builds dist/Samwaad/Samwaad.exe (one-folder, native to the build machine:
# build on the Snapdragon laptop for an ARM64 exe, on any x64 PC for x64).
#   .venv\Scripts\pip install pyinstaller
#   .venv\Scripts\pyinstaller packaging\samwaad.spec --noconfirm
# Then wrap it in an installer with packaging\installer.iss (Inno Setup 6).
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs, collect_submodules

ROOT = Path(SPECPATH).parent
hidden = collect_submodules("samwaad") + collect_submodules("uvicorn") + ["onnxruntime_qnn"]
datas = [
    (str(ROOT / "samwaad" / "web"), "samwaad/web"),
    (str(ROOT / "config.yaml"), "."),
    (str(ROOT / "samples"), "samples"),
    (str(ROOT / "benchmarks" / "aihub_published.json"), "benchmarks"),
]
datas += collect_data_files("transformers", include_py_files=False)
binaries = collect_dynamic_libs("onnxruntime")
try:  # QNN plugin EP (Snapdragon builds)
    binaries += collect_dynamic_libs("onnxruntime_qnn")
    datas += collect_data_files("onnxruntime_qnn")
except Exception:
    pass

a = Analysis([str(ROOT / "packaging" / "launcher.py")], pathex=[str(ROOT)], binaries=binaries, datas=datas,
             hiddenimports=hidden, excludes=["torch", "tensorflow", "matplotlib", "IPython"], noarchive=False)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="Samwaad", console=False,
          icon=str(ROOT / "samwaad" / "web" / "icon.ico"))
coll = COLLECT(exe, a.binaries, a.datas, name="Samwaad")
