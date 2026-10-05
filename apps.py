"""
App launcher — maps a spoken/typed query to an installed application.

Exposes two functions used by jarvis.py:

    find_app(query) -> (key, score)   # key is a display name, score a confidence
    open_app(query) -> bool           # True if the app was launched

Applications are discovered from the freedesktop .desktop entries in
/usr/share/applications and ~/.local/share/applications, plus a small
table of common terminal binaries that have no .desktop file.
"""

import glob
import os
import re
import shlex
import shutil
import subprocess
from typing import Dict, List, Optional, Tuple

# Directories scanned for .desktop entries.
DESKTOP_DIRS = (
    os.path.expanduser("~/.local/share/applications"),
    "/usr/share/applications",
    "/usr/local/share/applications",
    os.path.expanduser("~/.local/share/flatpak/exports/share/applications"),
    "/var/lib/flatpak/exports/share/applications",
)

# Binaries that are commonly wanted by voice but ship no .desktop entry.
EXTRA_APPS: Dict[str, List[str]] = {
    "Terminal": ["ghostty", "kitty", "alacritty", "gnome-terminal", "konsole", "xterm"],
    "Files": ["dolphin", "nautilus", "thunar", "pcmanfm"],
    "Text Editor": ["gedit", "kate", "nano"],
    "Video Editor": ["kdenlive", "shotcut", "olive-editor"],
    "Music Player": ["spotify", "rhythmbox", "mpv"],
    "Image Viewer": ["eog", "shotwell", "gwenview"],
    "Calculator": ["gnome-calculator", "kcalc", "galculator"],
}

# Words that carry no meaning when matching an app name.
STOPWORDS = {
    "open", "launch", "start", "the", "a", "an", "my", "please", "for", "me",
    "app", "application", "program", "run", "and", "of", "jarvis", "sir",
}

_apps: Optional[Dict[str, str]] = None


def _parse_desktop_file(path: str) -> Optional[Tuple[str, str]]:
    """Return (name, exec_command) for a .desktop file, or None to skip it."""
    name = None
    exec_cmd = None
    hidden = False
    no_display = False
    in_entry = False
    try:
        with open(path, encoding="utf-8", errors="ignore") as f:
            for line in f:
                line = line.strip()
                if line.startswith("[") and line.endswith("]"):
                    # Keys must belong to [Desktop Entry]; other groups
                    # (e.g. [Desktop Action new-window]) end the section.
                    if in_entry:
                        break
                    in_entry = line.lower() == "[desktop entry]"
                    continue
                if not in_entry:
                    continue
                if line.startswith("Name="):
                    name = line[5:].strip()
                elif line.startswith("Exec="):
                    exec_cmd = line[5:].strip()
                elif line.startswith("Hidden="):
                    hidden = line[7:].strip().lower() == "true"
                elif line.startswith("NoDisplay="):
                    no_display = line[10:].strip().lower() == "true"
    except OSError:
        return None

    if not name or not exec_cmd or hidden or no_display:
        return None
    return name, exec_cmd


def _strip_field_codes(exec_cmd: str) -> str:
    """Remove %f/%u/%U-style field codes and desktop-entry keywords."""
    exec_cmd = re.sub(r"%\w", "", exec_cmd)
    try:
        parts = shlex.split(exec_cmd)
    except ValueError:
        parts = exec_cmd.split()
    drop = {"--", "-i", "--icon", "-c", "--class"}
    kept = [p for p in parts if p not in drop]
    return " ".join(shlex.quote(p) for p in kept)


def _build_index() -> Dict[str, str]:
    index: Dict[str, str] = {}
    for directory in DESKTOP_DIRS:
        for path in glob.glob(os.path.join(directory, "*.desktop")):
            parsed = _parse_desktop_file(path)
            if parsed:
                name, exec_cmd = parsed
                index.setdefault(name, _strip_field_codes(exec_cmd))

    for name, candidates in EXTRA_APPS.items():
        if name in index:
            continue
        for binary in candidates:
            if shutil.which(binary):
                index[name] = binary
                break
    return index


def _all_apps() -> Dict[str, str]:
    global _apps
    if _apps is None:
        _apps = _build_index()
    return _apps


def _score(query: str, name: str) -> float:
    """Confidence that `query` refers to the app called `name`."""
    q = query.lower()
    n = name.lower()
    words = [w for w in re.split(r"[\s\-_]+", q) if w and w not in STOPWORDS]
    if not words:
        return 0.0

    best = 0.0
    for word in words:
        if word == n:
            best = max(best, 1.0)
        elif n.startswith(word) or word.startswith(n):
            best = max(best, 0.8)
        elif word in n:
            best = max(best, 0.6)
        elif n in word:
            best = max(best, 0.5)

    # All significant words matching beats any single word matching.
    if len(words) > 1 and all(
        w in n or any(w in part for part in re.split(r"[\s\-_]+", n))
        for w in words
    ):
        best = max(best, 0.9)
    return best


def find_app(query: str) -> Tuple[Optional[str], float]:
    """Best matching app for `query`, as (display_name, score).

    Returns (None, 0.0) when nothing scores above the threshold.
    """
    apps = _all_apps()
    if not apps:
        return None, 0.0

    best_name, best_score = None, 0.0
    for name in apps:
        s = _score(query, name)
        if s > best_score:
            best_name, best_score = name, s

    if best_name and best_score >= 0.5:
        return best_name, round(best_score, 2)
    return None, 0.0


def open_app(query: str) -> bool:
    """Launch the app matching `query`. Returns True on success."""
    name, _score_value = find_app(query)
    if not name:
        return False

    cmd = _all_apps().get(name)
    if not cmd:
        return False

    try:
        subprocess.Popen(
            cmd,
            shell=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        return True
    except OSError:
        return False


def list_apps() -> List[str]:
    """Every app Jarvis knows how to open."""
    return sorted(_all_apps().keys())


if __name__ == "__main__":
    for _app in list_apps():
        print(_app)