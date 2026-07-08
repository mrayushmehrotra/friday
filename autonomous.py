"""
Autonomous Agent — Jarvis takes over your PC for a set duration.
Generates plans using the LLM and executes them with human-like
mouse / keyboard behavior, as if a real person were working.
"""

import json
import os
import random
import subprocess
import time
import webbrowser

from enhanced import _query_llm
from helpers import log_event, speak

# ---------------------------------------------------------------------------
#  Globals – can be set from outside (e.g. from the voice loop) to stop
# ---------------------------------------------------------------------------

stop_requested = False
auto_active = False

# ---------------------------------------------------------------------------
#  Configuration
# ---------------------------------------------------------------------------

MIN_DELAY = 3
MAX_DELAY = 10

_IS_WAYLAND = os.environ.get("XDG_SESSION_TYPE") == "wayland"

# ---------------------------------------------------------------------------
#  Helpers for X11 vs Wayland
# ---------------------------------------------------------------------------


def _wtype(text: str):
    """Type via wtype (Wayland)."""
    subprocess.run(["wtype", text], capture_output=True)


def _wtype_hotkey(*keys):
    """Press hotkey via wtype (Wayland)."""
    if not keys:
        return
    mods = [k.lower() for k in keys[:-1]]
    main_key = keys[-1].lower()
    cmd = ["wtype"]
    for m in mods:
        cmd += ["-M", m]
    cmd += ["-k", main_key]
    for m in reversed(mods):
        cmd += ["-m", m]
    subprocess.run(cmd, capture_output=True)


# ---------------------------------------------------------------------------
#  Human-like behaviour primitives
# ---------------------------------------------------------------------------


def _sleep(min_s=MIN_DELAY, max_s=MAX_DELAY):
    time.sleep(random.uniform(min_s, max_s))


def _jitter():
    if _IS_WAYLAND:
        return
    try:
        import pyautogui
        pyautogui.moveRel(
            random.randint(-5, 5),
            random.randint(-5, 5),
            duration=random.uniform(0.05, 0.2),
        )
    except ImportError:
        pass


def _type_text(text: str):
    if _IS_WAYLAND:
        _wtype(text)
        return
    try:
        import pyautogui
        for ch in text:
            pyautogui.write(ch, interval=random.uniform(0.03, 0.12))
            if random.random() < 0.02:
                time.sleep(random.uniform(0.3, 0.8))
    except ImportError:
        pass


def _press_hotkey(*keys):
    if _IS_WAYLAND:
        _wtype_hotkey(*keys)
        return
    try:
        import pyautogui
        pyautogui.hotkey(*keys)
    except ImportError:
        pass


def _click():
    if _IS_WAYLAND:
        return
    try:
        import pyautogui
        pyautogui.click()
    except ImportError:
        pass


def _scroll(clicks: int):
    if _IS_WAYLAND:
        return
    try:
        import pyautogui
        pyautogui.scroll(clicks)
    except ImportError:
        pass


# ---------------------------------------------------------------------------
#  Action dispatch
# ---------------------------------------------------------------------------

HANDLERS: dict[str, callable] = {}


def _register_action(name: str):
    def wrapper(fn):
        HANDLERS[name] = fn
        return fn
    return wrapper


@_register_action("open_url")
def _handle_open_url(params):
    webbrowser.open_new_tab(params["url"])


@_register_action("type")
def _handle_type(params):
    _type_text(params["text"])


@_register_action("hotkey")
def _handle_hotkey(params):
    keys = params["keys"] if isinstance(params["keys"], list) else params["keys"].split("+")
    _press_hotkey(*keys)


@_register_action("click")
def _handle_click(_params):
    _click()


@_register_action("scroll")
def _handle_scroll(params):
    _scroll(params["clicks"])


@_register_action("wait")
def _handle_wait(params):
    time.sleep(params["seconds"])


@_register_action("speak")
def _handle_speak(params):
    speak(params["message"])


@_register_action("run")
def _handle_run(params):
    subprocess.Popen(
        params["cmd"], shell=True,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )


@_register_action("launch")
def _handle_launch(params):
    subprocess.Popen(
        [params["app"]],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )


@_register_action("move_mouse")
def _handle_move_mouse(params):
    try:
        import pyautogui
        pyautogui.moveTo(
            params.get("x", 500), params.get("y", 400),
            duration=random.uniform(0.3, 1.0),
        )
    except ImportError:
        pass


def execute_step(step: dict) -> bool:
    kind = step.get("action", "")
    params = {k: v for k, v in step.items() if k not in ("action", "description")}
    handler = HANDLERS.get(kind)
    if not handler:
        log_event(f"Unknown action: {kind}", "error")
        return False
    try:
        desc = step.get("description", kind)
        print(f"  \u2192 {desc}")
        log_event(f"Auto step: {desc}")
        handler(params)
        return True
    except Exception as e:
        log_event(f"Step '{kind}' failed: {e}", "error")
        return False


# ---------------------------------------------------------------------------
#  Plan generation via LLM
# ---------------------------------------------------------------------------

_PLAN_PROMPT = """\
You are an AI desktop assistant controlling a Linux PC. Generate a JSON array of \
actions to accomplish the user's goal within {dm} minutes.

Available actions:
  {{"action":"open_url","url":"https://..."}}
  {{"action":"type","text":"text to type"}}
  {{"action":"hotkey","keys":["ctrl","c"]}}
  {{"action":"click"}}
  {{"action":"scroll","clicks":-3}}
  {{"action":"move_mouse","x":500,"y":400}}
  {{"action":"wait","seconds":5}}
  {{"action":"speak","message":"..."}}
  {{"action":"run","cmd":"shell command"}}
  {{"action":"launch","app":"firefox"}}

Rules:
- Output ONLY a valid JSON array. No markdown, no extra text.
- Add wait steps after opening URLs or launching apps.
- Generate enough steps to fill {dm} minutes (each step ~5-10 s with delays).
- Vary actions to look like a real human working.
- Use keyboard shortcuts (hotkey) over mouse when possible.

User goal: {goal}
Actions:"""


def generate_plan(goal: str, duration_minutes: int) -> list[dict]:
    prompt = _PLAN_PROMPT.format(dm=duration_minutes, goal=goal)
    result = _query_llm(prompt)
    if not result:
        return []
    try:
        start = result.find("[")
        end = result.rfind("]") + 1
        if start >= 0 and end > start:
            plan = json.loads(result[start:end])
            if isinstance(plan, list):
                return plan
    except (json.JSONDecodeError, ValueError) as e:
        log_event(f"Plan JSON error: {e}", "error")
    return []


# ---------------------------------------------------------------------------
#  Main autonomous loop
# ---------------------------------------------------------------------------


def run_autonomous(goal: str, duration_minutes: int = 30):
    """Blocking call — takes over the PC for the given duration."""
    global stop_requested, auto_active
    stop_requested = False
    auto_active = True

    start_time = time.time()
    deadline = start_time + duration_minutes * 60

    speak(f"Taking control for {duration_minutes} minutes. Goal: {goal}")

    while time.time() < deadline:
        if stop_requested:
            speak("Autonomous mode stopped.")
            auto_active = False
            return

        remaining_seconds = int(deadline - time.time())
        remaining_minutes = max(1, remaining_seconds // 60)

        plan = generate_plan(goal, remaining_minutes)
        if not plan:
            speak("Planning failed. Retrying...")
            _sleep(5, 10)
            continue

        print(f"\n{'='*50}")
        print(f"Plan: {len(plan)} steps (\u2248{remaining_minutes} min left)")
        print(f"{'='*50}")

        for i, step in enumerate(plan):
            if time.time() >= deadline or stop_requested:
                break

            execute_step(step)

            kind = step.get("action", "")
            if kind not in ("wait", "speak") and i < len(plan) - 1:
                _sleep()
                if random.random() < 0.3:
                    _jitter()

        print(f"\n  \u2713 Round complete")

    auto_active = False
    speak(f"Session complete. Worked for {duration_minutes} minutes on {goal}.")
