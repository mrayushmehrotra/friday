"""
YouTube Uploader — uploads videos to YouTube via OAuth2 + YouTube Data API v3.
Opens a Tkinter form to collect metadata (title, description, tags, etc.).
"""

import os
import pickle
import re
import subprocess
import threading

from helpers import log_event, speak

# ---------------------------------------------------------------------------
#  Paths
# ---------------------------------------------------------------------------

_CONFIG_DIR = os.path.expanduser("~/.jarvis")
_TOKEN_PATH = os.path.join(_CONFIG_DIR, "youtube_token.pickle")
_CLIENT_SECRET_PATH = os.path.join(_CONFIG_DIR, "client_secret.json")
os.makedirs(_CONFIG_DIR, exist_ok=True)

_YOUTUBE_SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]


# ---------------------------------------------------------------------------
#  OAuth2 helpers
# ---------------------------------------------------------------------------


def _get_authenticated_service():
    """Authenticate and return a YouTube API service instance."""
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow

    creds = None
    if os.path.exists(_TOKEN_PATH):
        try:
            with open(_TOKEN_PATH, "rb") as f:
                creds = pickle.load(f)
        except Exception:
            creds = None

    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
        except Exception:
            creds = None

    if not creds or not creds.valid:
        if not os.path.exists(_CLIENT_SECRET_PATH):
            print("\n  Missing client_secret.json")
            print("  1. Go to https://console.cloud.google.com/apis/credentials")
            print("  2. Create OAuth 2.0 Client ID → Desktop App")
            print(f"  3. Download JSON → save as {_CLIENT_SECRET_PATH}")
            raise FileNotFoundError(str(_CLIENT_SECRET_PATH))

        flow = InstalledAppFlow.from_client_secrets_file(
            _CLIENT_SECRET_PATH, _YOUTUBE_SCOPES
        )

        # Generate the auth URL (don't rely on webbrowser on Wayland)
        import webbrowser

        auth_url, _ = flow.authorization_url(
            access_type="offline", include_granted_scopes="true"
        )

        print("\n" + "=" * 60)
        print("  FIRST-TIME YOUTUBE AUTHENTICATION")
        print("=" * 60)
        print(f"  Opening browser to sign in with Google...")
        print(f"  If browser doesn't open, visit this URL:")
        print(f"  {auth_url}")
        print("=" * 60 + "\n")

        try:
            opened = webbrowser.open(auth_url)
            if not opened:
                subprocess.Popen(
                    ["xdg-open", auth_url],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
        except Exception:
            pass

        creds = flow.run_local_server(port=0, open_browser=False)

        with open(_TOKEN_PATH, "wb") as f:
            pickle.dump(creds, f)
        print("  ✓ Authentication successful. Token saved.\n")

    from googleapiclient.discovery import build

    return build("youtube", "v3", credentials=creds)


# ---------------------------------------------------------------------------
#  Upload function
# ---------------------------------------------------------------------------

_CATEGORY_MAP = {
    "Film & Animation": 1,
    "Autos & Vehicles": 2,
    "Music": 10,
    "Pets & Animals": 15,
    "Sports": 17,
    "Short Movies": 18,
    "Travel & Events": 19,
    "Gaming": 20,
    "Videoblogging": 21,
    "People & Blogs": 22,
    "Comedy": 23,
    "Entertainment": 24,
    "News & Politics": 25,
    "Howto & Style": 26,
    "Education": 27,
    "Science & Technology": 28,
    "Nonprofits & Activism": 29,
    "Movies": 30,
    "Anime/Animation": 31,
    "Action/Adventure": 32,
    "Classics": 33,
    "Documentary": 35,
    "Drama": 36,
    "Family": 37,
    "Foreign": 38,
    "Horror": 39,
    "Sci-Fi/Fantasy": 40,
    "Thriller": 41,
    "Shorts": 42,
    "Shows": 43,
    "Trailers": 44,
}

_CATEGORY_VOICE_MAP = {str(v).lower(): k for k, v in _CATEGORY_MAP.items()}


def upload_video(
    file_path: str,
    title: str,
    description: str = "",
    tags: list[str] | None = None,
    category_id: int = 24,
    privacy_status: str = "private",
) -> str | None:
    """Upload a video to YouTube. Returns the video URL or None on failure."""
    from googleapiclient.http import MediaFileUpload

    try:
        youtube = _get_authenticated_service()
    except FileNotFoundError:
        speak("YouTube client_secret.json not found. Check the terminal.")
        return None
    except Exception as e:
        log_event(f"YouTube auth error: {e}", "error")
        print(f"\n  YouTube auth error: {e}")
        speak("YouTube authentication failed. Check the terminal.")
        return None

    body = {
        "snippet": {
            "title": title,
            "description": description,
            "tags": tags or [],
            "categoryId": str(category_id),
        },
        "status": {
            "privacyStatus": privacy_status,
            "selfDeclaredMadeForKids": False,
        },
    }

    media = MediaFileUpload(file_path, chunksize=1024 * 1024, resumable=True)

    request = youtube.videos().insert(
        part="snippet,status",
        body=body,
        media_body=media,
    )

    speak("Uploading...")
    response = None
    try:
        response = request.execute()
    except Exception as e:
        log_event(f"YouTube upload failed: {e}", "error")
        print(f"\n  Upload error: {e}")
        speak("Upload failed.")
        return None

    if response and response.get("id"):
        video_id = response["id"]
        url = f"https://youtu.be/{video_id}"
        log_event(f"Uploaded: {url}")
        return url
    return None


# ---------------------------------------------------------------------------
#  Voice-driven metadata collection
# ---------------------------------------------------------------------------


def _parse_category(text: str) -> int:
    """Try to match spoken category to a YouTube category ID."""
    text = text.lower().strip()
    for name, cid in _CATEGORY_MAP.items():
        if text in name.lower():
            return cid
    for num_str, name in _CATEGORY_VOICE_MAP.items():
        if text == num_str or text.startswith(num_str):
            return int(num_str)
    return 24


_VIDEOS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "videos")


def _search_videos_dir(keyword: str) -> str | None:
    """Search ./videos/ for a file whose name contains keyword. Returns full path or None."""
    if not os.path.isdir(_VIDEOS_DIR):
        return None
    matches = []
    for f in os.listdir(_VIDEOS_DIR):
        if keyword.lower() in f.lower():
            full = os.path.join(_VIDEOS_DIR, f)
            if os.path.isfile(full):
                matches.append(full)
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        print("\n  Multiple matches found:")
        for i, p in enumerate(matches, 1):
            print(f"  {i}. {os.path.basename(p)}")
        choice = _cli_input(f"Pick 1-{len(matches)} or press Enter to skip:")
        if choice.isdigit() and 1 <= int(choice) <= len(matches):
            return matches[int(choice) - 1]
    return None


def _resolve_path(inp: str) -> str:
    """Expand ~ and check common video directories."""
    expanded = os.path.expanduser(inp.strip())
    if os.path.exists(expanded):
        return os.path.abspath(expanded)
    base = os.path.expanduser("~/Videos")
    candidate = os.path.join(base, expanded)
    if os.path.exists(candidate):
        return os.path.abspath(candidate)
    base2 = os.path.expanduser("~/Downloads")
    candidate2 = os.path.join(base2, expanded)
    if os.path.exists(candidate2):
        return os.path.abspath(candidate2)
    for root, _dirs, files in os.walk(os.path.expanduser("~/Videos")):
        for f in files:
            if expanded.lower() in f.lower():
                return os.path.join(root, f)
    return expanded


# ---------------------------------------------------------------------------
#  Main entry — called from jarvis.py
# ---------------------------------------------------------------------------


def run(query: str = ""):
    """Parse query, auto-search ./videos/, then open a yad form for metadata."""
    q = query.lower()

    # --- Query parsing ---
    file_path = ""
    title = ""
    description = ""
    tags_raw = ""
    category_id = 24
    privacy_status = "private"

    path_match = re.search(r"file[=:]?\s*(\S+)", query)
    if path_match:
        file_path = _resolve_path(path_match.group(1))

    title_match = re.search(r"title[=:]?\s*\"(.+?)\"", query)
    if title_match:
        title = title_match.group(1)

    desc_match = re.search(r"desc(?:ription)?[=:]?\s*\"(.+?)\"", query)
    if desc_match:
        description = desc_match.group(1)

    tags_match = re.search(r"tags[=:]?\s*\"(.+?)\"", query)
    if tags_match:
        tags_raw = tags_match.group(1)

    if "private" in q:
        privacy_status = "private"
    elif "unlisted" in q:
        privacy_status = "unlisted"
    elif "public" in q:
        privacy_status = "public"

    for name, cid in _CATEGORY_MAP.items():
        if name.lower() in q:
            category_id = cid
            break

    if not file_path:
        video_keyword = ""
        upload_match = re.search(r"upload\s+(.+?)\s+video", q)
        if upload_match:
            video_keyword = upload_match.group(1).strip()
        else:
            video_match = re.search(r"(.+?)\s+video", q)
            if video_match:
                kw = video_match.group(1).strip()
                if kw not in ("upload", "a", "the", "this", "that", "my", "our"):
                    video_keyword = kw
        if video_keyword:
            found = _search_videos_dir(video_keyword)
            if found:
                file_path = found
                if not title:
                    title = os.path.splitext(os.path.basename(file_path))[0]

    # --- yad form ---
    cat_list = "!".join(_CATEGORY_MAP.keys())
    cat_default = next(
        (n for n, c in _CATEGORY_MAP.items() if c == category_id), "Entertainment"
    )

    cmd = [
        "yad",
        "--form",
        "--title=Jarvis — YouTube Uploader",
        "--width=640",
        "--height=480",
        "--center",
        "--on-top",
        "--separator=||",
        "--field=Video file:FL",
        file_path or "",
        "--field=Title",
        title or "",
        "--field=Description:TXT",
        description or "",
        "--field=Tags (comma-separated)",
        tags_raw or "",
        "--field=Category:CB",
        f"{cat_default}!{cat_list}",
        "--field=Privacy:CB",
        f"{privacy_status}!public!unlisted!private",
        "--button=Upload and Exit:0",
        "--button=Cancel:1",
    ]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    except FileNotFoundError:
        speak("yad is not installed. Install it with: sudo pacman -S yad")
        return
    except subprocess.TimeoutExpired:
        speak("Form timed out.")
        return

    if result.returncode != 0:
        speak("Upload cancelled.")
        return

    parts = [p.strip() for p in result.stdout.strip().split("||")]
    if len(parts) < 6:
        print(f"  yad returned: {result.stdout}")
        return

    file_path = parts[0]
    title = parts[1]
    description = parts[2]
    tags_raw = parts[3]
    cat_str = parts[4]
    privacy_status = parts[5]

    if not file_path or not os.path.exists(file_path):
        speak("No valid video file selected.")
        return
    if not title:
        speak("Title is required.")
        return

    tags = [t.strip() for t in tags_raw.split(",") if t.strip()]
    cid = _CATEGORY_MAP.get(cat_str, 24)

    print(f"  File: {os.path.basename(file_path)}")
    print(f"  Title: {title}")
    print(f"  Privacy: {privacy_status}")

    # --- Upload with progress ---
    progress_cmd = [
        "yad",
        "--progress",
        "--title=Jarvis — Uploading",
        "--text=Authenticating with YouTube...",
        "--percentage=0",
        "--auto-close",
        "--pulsate",
        "--center",
        "--on-top",
        "--button=Cancel:1",
    ]
    progress_proc = subprocess.Popen(
        progress_cmd,
        stdin=subprocess.PIPE,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    def update_progress(pct: int):
        if progress_proc.poll() is not None:
            return
        progress_proc.stdin.write(f"{pct}\n".encode())
        progress_proc.stdin.flush()

    def close_progress():
        if progress_proc.poll() is None:
            progress_proc.stdin.close()
            progress_proc.wait()

    def upload_and_report():
        nonlocal url
        url = upload_video(file_path, title, description, tags, cid, privacy_status)
        finished.set()

    url = None
    finished = threading.Event()
    threading.Thread(target=upload_and_report, daemon=True).start()

    # Poll progress
    import time as _time

    while not finished.is_set():
        if progress_proc.poll() is not None:
            break
        _time.sleep(0.5)

    close_progress()

    if url:
        speak("Video uploaded successfully.")
        import pyperclip

        try:
            pyperclip.copy(url)
        except Exception:
            pass
        subprocess.Popen(
            [
                "yad",
                "--info",
                "--title=Jarvis",
                "--text",
                f"Uploaded!\n\n{url}\n\nLink copied to clipboard.",
                "--center",
                "--on-top",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    else:
        speak("Upload failed.")
        subprocess.Popen(
            [
                "yad",
                "--error",
                "--title=Jarvis",
                "--text",
                "Upload failed. Check the logs.",
                "--center",
                "--on-top",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
