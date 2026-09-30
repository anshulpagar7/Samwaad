"""Entry point for the packaged Samwaad.exe (PyInstaller).

Runs from the install folder so config.yaml, models/ and sessions/ sit next to the exe
(user data under %LOCALAPPDATA%\\Samwaad when the install folder isn't writable).
"""
import os
import sys
from pathlib import Path

if getattr(sys, "frozen", False):
    base = Path(sys.executable).parent
    os.chdir(base)
    try:
        (base / ".write_test").touch()
        (base / ".write_test").unlink()
    except OSError:  # installed under Program Files -> keep lectures + accounts in LocalAppData
        data = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "Samwaad"
        data.mkdir(parents=True, exist_ok=True)
        sys.argv += ["-o", f"store.dir={data / 'sessions'}", "-o", f"auth.dir={data / 'data'}"]

from samwaad.__main__ import main  # noqa: E402

if __name__ == "__main__":
    if len(sys.argv) == 1 or sys.argv[1].startswith("-"):
        sys.argv.insert(1, "app")
    main()
