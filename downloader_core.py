import os
import re
import json
import shutil
import urllib.request
import urllib.error
from urllib.parse import urlparse, quote
from typing import Dict, Any, Callable, Optional, List

import yt_dlp


# ---------------------------------------------------------------------------
# FFmpeg discovery – cross-platform, no hardcoded .exe paths
# ---------------------------------------------------------------------------

def find_ffmpeg() -> Optional[str]:
    """
    Return the *directory* that contains the ffmpeg binary, or None.
    Search order:
      1. System PATH  (works on Linux/macOS/Windows)
      2. imageio-ffmpeg bundled binary (optional dependency)
    """
    path_ffmpeg = shutil.which("ffmpeg")
    if path_ffmpeg:
        return os.path.dirname(path_ffmpeg)

    try:
        import imageio_ffmpeg
        exe = imageio_ffmpeg.get_ffmpeg_exe()
        if exe and os.path.isfile(exe):
            return os.path.dirname(exe)
    except Exception:
        pass

    return None


# ---------------------------------------------------------------------------
# Utility formatters
# ---------------------------------------------------------------------------

def format_bytes(size_bytes: Optional[int]) -> str:
    if not size_bytes or size_bytes <= 0:
        return "Unknown size"
    if size_bytes >= 1024 ** 3:
        return f"{size_bytes / 1024**3:.2f} GB"
    if size_bytes >= 1024 ** 2:
        return f"{size_bytes / 1024**2:.1f} MB"
    if size_bytes >= 1024:
        return f"{size_bytes / 1024:.0f} KB"
    return f"{size_bytes} B"


def format_duration(seconds: Optional[int]) -> str:
    if not seconds or seconds <= 0:
        return "Ready"
    m, s = divmod(seconds, 60)
    h, m = divmod(m, 60)
    if h > 0:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


# ---------------------------------------------------------------------------
# Quality presets & size estimations
# ---------------------------------------------------------------------------

def calculate_sizes_and_options(duration_sec: int) -> List[Dict[str, Any]]:
    dur = max(duration_sec, 180)

    presets = [
        {
            "id": "2160",
            "label": "4K Ultra HD (2160p)",
            "res_text": "3840 x 2160 • 4K UHD",
            "badge": "4K UHD",
            "badge_color": "gold",
            "bitrate": "24 Mbps",
            "bitrate_mbps": 24.0,
            "codec": "MP4 (H.264/AAC High Profile)",
            "desc": "Ultra Sharp 4K Quality",
            "type": "video",
        },
        {
            "id": "1440",
            "label": "2K Quad HD (1440p)",
            "res_text": "2560 x 1440 • 2K QHD",
            "badge": "2K QHD",
            "badge_color": "purple",
            "bitrate": "13 Mbps",
            "bitrate_mbps": 13.0,
            "codec": "MP4 (H.264/AAC)",
            "desc": "Crisp Quad HD quality",
            "type": "video",
        },
        {
            "id": "1080",
            "label": "Full HD (1080p)",
            "res_text": "1920 x 1080 • FHD",
            "badge": "1080p FHD",
            "badge_color": "cyan",
            "bitrate": "4.8 Mbps",
            "bitrate_mbps": 4.8,
            "codec": "MP4 (Universal Compatible)",
            "desc": "High Definition 1080p",
            "type": "video",
        },
        {
            "id": "720",
            "label": "HD (720p)",
            "res_text": "1280 x 720 • HD",
            "badge": "720p HD",
            "badge_color": "blue",
            "bitrate": "2.4 Mbps",
            "bitrate_mbps": 2.4,
            "codec": "MP4 (Fast Download)",
            "desc": "Standard HD quality",
            "type": "video",
        },
        {
            "id": "480",
            "label": "SD (480p)",
            "res_text": "854 x 480 • SD",
            "badge": "480p SD",
            "badge_color": "slate",
            "bitrate": "1.1 Mbps",
            "bitrate_mbps": 1.1,
            "codec": "MP4 (Data Saver)",
            "desc": "Standard Definition",
            "type": "video",
        },
        {
            "id": "360",
            "label": "Low (360p)",
            "res_text": "640 x 360 • Low",
            "badge": "360p",
            "badge_color": "gray",
            "bitrate": "0.55 Mbps",
            "bitrate_mbps": 0.55,
            "codec": "MP4 (Minimal Size)",
            "desc": "Lightest video option",
            "type": "video",
        },
        {
            "id": "best",
            "label": "Best Available (Auto)",
            "res_text": "Original Resolution",
            "badge": "MAX QUALITY",
            "badge_color": "indigo",
            "bitrate": "Auto Bitrate",
            "bitrate_mbps": 6.5,
            "codec": "MP4 (Direct Stream)",
            "desc": "Highest uploaded resolution",
            "type": "video",
        },
        {
            "id": "mp3",
            "label": "🎵 MP3 Audio (High Quality)",
            "res_text": "Audio Only • 320 kbps",
            "badge": "HQ AUDIO",
            "badge_color": "emerald",
            "bitrate": "320 kbps CBR",
            "bitrate_mbps": 0.32,
            "codec": "MP3 (320kbps Studio Audio)",
            "desc": "Pure crystal-clear audio",
            "type": "audio",
        },
    ]

    options = []
    for p in presets:
        bytes_val = int((p["bitrate_mbps"] * 1_000_000 / 8) * dur)
        size_display = format_bytes(bytes_val)
        est_sec = max(int(bytes_val / (25 * 1024 * 1024)), 1)
        est_time_str = (
            f"~ {est_sec} sec" if est_sec < 60 else f"~ {est_sec // 60}m {est_sec % 60}s"
        )
        opt = dict(p)
        opt["size_bytes"] = bytes_val
        opt["size_str"] = size_display
        opt["est_time"] = est_time_str
        options.append(opt)

    return options


# ---------------------------------------------------------------------------
# oEmbed helper – pure Python urllib, no curl dependency
# ---------------------------------------------------------------------------

def _fetch_oembed(oembed_url: str, timeout: float) -> Optional[Dict]:
    """Fetch a JSON oEmbed endpoint. Returns parsed dict or None."""
    try:
        req = urllib.request.Request(
            oembed_url,
            headers={"User-Agent": "NexusDownloader/2.0"},
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
        if raw.strip().startswith("{"):
            return json.loads(raw)
    except Exception:
        pass
    return None


# ---------------------------------------------------------------------------
# Main metadata extraction
# ---------------------------------------------------------------------------

def get_video_info(url: str, timeout: float = 3.0) -> Dict[str, Any]:
    """
    Fast link recogniser – no subprocess calls, pure Python networking.
    Returns title, thumbnail, embed_url, quality options, etc.
    """
    url = url.strip()
    parsed = urlparse(url)
    domain = parsed.netloc.lower().replace("www.", "")

    title = "Online Video"
    uploader = "Creator"
    thumbnail = ""
    platform = "Web"
    duration_sec = 180
    embed_url = ""

    # ── 1. YouTube ──────────────────────────────────────────────────────────
    yt_id_match = re.search(r'(?:v=|/|shorts/)([0-9A-Za-z_-]{11})', url)
    if "youtube.com" in domain or "youtu.be" in domain:
        platform = "YouTube"
        vid_id = yt_id_match.group(1) if yt_id_match else None
        if vid_id:
            thumbnail = f"https://i.ytimg.com/vi/{vid_id}/hqdefault.jpg"
            title = f"YouTube Video ({vid_id})"
            embed_url = (
                f"https://www.youtube.com/embed/{vid_id}"
                "?autoplay=1&rel=0&modestbranding=1"
            )
        encoded = quote(url, safe="")
        data = _fetch_oembed(
            f"https://www.youtube.com/oembed?url={encoded}&format=json",
            timeout,
        )
        if data:
            title = data.get("title") or title
            uploader = data.get("author_name") or uploader
            thumbnail = data.get("thumbnail_url") or thumbnail

    # ── 2. Vimeo ────────────────────────────────────────────────────────────
    elif "vimeo.com" in domain:
        platform = "Vimeo"
        title = "Vimeo Video"
        vm = re.search(r'vimeo\.com/(?:video/)?([0-9]+)', url)
        if vm:
            embed_url = f"https://player.vimeo.com/video/{vm.group(1)}?autoplay=1"
        encoded = quote(url, safe="")
        data = _fetch_oembed(
            f"https://vimeo.com/api/oembed.json?url={encoded}",
            timeout,
        )
        if data:
            title = data.get("title") or title
            uploader = data.get("author_name") or uploader
            thumbnail = data.get("thumbnail_url") or thumbnail

    # ── 3. TikTok ───────────────────────────────────────────────────────────
    elif "tiktok.com" in domain:
        platform = "TikTok"
        title = "TikTok Video"
        uploader = "TikTok Creator"
        duration_sec = 60
        tt = re.search(r'video/(\d+)', url)
        if tt:
            embed_url = f"https://www.tiktok.com/embed/v2/{tt.group(1)}"
        encoded = quote(url, safe="")
        data = _fetch_oembed(
            f"https://www.tiktok.com/oembed?url={encoded}",
            timeout,
        )
        if data:
            title = data.get("title") or title
            uploader = data.get("author_name") or uploader
            thumbnail = data.get("thumbnail_url") or thumbnail

    # ── 4. Dailymotion ──────────────────────────────────────────────────────
    elif "dailymotion.com" in domain or "dai.ly" in domain:
        platform = "Dailymotion"
        title = "Dailymotion Video"
        dm = re.search(r'(?:video/|dai\.ly/)([a-zA-Z0-9]+)', url)
        if dm:
            embed_url = (
                f"https://www.dailymotion.com/embed/video/{dm.group(1)}?autoplay=1"
            )

    # ── 5. Facebook / Instagram ─────────────────────────────────────────────
    elif "facebook.com" in domain or "fb.watch" in domain:
        platform = "Facebook"
        title = "Facebook Video / Reel"
        uploader = "Facebook Creator"
        duration_sec = 120
    elif "instagram.com" in domain:
        platform = "Instagram"
        title = "Instagram Video / Reel"
        uploader = "Instagram Creator"
        duration_sec = 60

    # ── 6. Twitter / X ──────────────────────────────────────────────────────
    elif "twitter.com" in domain or "x.com" in domain:
        platform = "Twitter / X"
        title = "Twitter / X Video"
        uploader = "X Creator"
        duration_sec = 90

    else:
        platform = domain.capitalize() if domain else "Web"
        title = f"{platform} Video"

    options = calculate_sizes_and_options(duration_sec)
    ffmpeg_ok = find_ffmpeg() is not None

    return {
        "url": url,
        "title": title,
        "platform": platform,
        "uploader": uploader,
        "thumbnail": thumbnail,
        "duration": format_duration(duration_sec),
        "duration_sec": duration_sec,
        "embed_url": embed_url,
        "options": options,
        "has_ffmpeg": ffmpeg_ok,
    }


# ---------------------------------------------------------------------------
# Downloader
# ---------------------------------------------------------------------------

def download_media(
    url: str,
    quality_id: str,
    output_dir: str,
    progress_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
) -> str:
    """Download video or extract MP3 audio using yt-dlp."""
    os.makedirs(output_dir, exist_ok=True)
    ffmpeg_dir = find_ffmpeg()

    def ydl_hook(d):
        if not progress_callback:
            return
        status = d.get("status")
        if status == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            downloaded = d.get("downloaded_bytes", 0)
            percent = (downloaded / total * 100) if total > 0 else 0
            speed = d.get("speed") or 0
            eta = d.get("eta") or 0
            progress_callback(
                {
                    "status": "downloading",
                    "percent": min(round(percent, 1), 100.0),
                    "speed": f"{speed / 1_048_576:.2f} MB/s" if speed else "Calculating...",
                    "eta": f"{int(eta)}s" if eta else "--",
                    "size": (
                        f"{format_bytes(downloaded)} / {format_bytes(total)}"
                        if total
                        else format_bytes(downloaded)
                    ),
                    "filename": os.path.basename(d.get("filename", "")),
                }
            )
        elif status == "finished":
            progress_callback(
                {"status": "processing", "percent": 100.0, "message": "Merging / Converting..."}
            )

    ydl_opts: Dict[str, Any] = {
        "outtmpl": os.path.join(output_dir, "%(title)s.%(ext)s"),
        "progress_hooks": [ydl_hook],
        "quiet": True,
        "no_warnings": True,
        # 'windowsfilenames' intentionally omitted – not safe on Linux
        "nocheckcertificate": True,
        "extractor_args": {
            "youtube": {"player_client": ["android", "ios", "web"]}
        },
    }

    if ffmpeg_dir:
        ydl_opts["ffmpeg_location"] = ffmpeg_dir

    if quality_id == "mp3":
        ydl_opts["format"] = "bestaudio/best"
        ydl_opts["postprocessors"] = [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "320",
            }
        ]
    elif quality_id == "best":
        ydl_opts["format"] = "bestvideo+bestaudio/best"
        ydl_opts["merge_output_format"] = "mp4"
    else:
        h = int(quality_id)
        ydl_opts["format"] = f"bestvideo[height<={h}]+bestaudio/best[height<={h}]/best"
        ydl_opts["merge_output_format"] = "mp4"

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.download([url])

    if progress_callback:
        progress_callback({"status": "completed", "percent": 100.0, "message": "Done! 🎉"})

    return output_dir
