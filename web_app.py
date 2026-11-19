"""
web_app.py – Flask-based Nexus Video & MP3 Studio
Works on Linux (Render, Railway, Fly.io, etc.) and Windows.
Reads PORT from environment variable; binds on 0.0.0.0.
No hardcoded Windows paths, no curl.exe, no os.startfile.
"""

import os
import threading
import subprocess
from flask import Flask, request, jsonify, Response

import downloader_core

# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------

current_download: dict = {
    "status": "idle",
    "percent": 0,
    "speed": "",
    "eta": "",
    "size": "",
    "filename": "",
    "message": "",
    "error": "",
}
download_lock = threading.Lock()

# Cloud-safe download directory: prefer /tmp on Linux, ~/Downloads elsewhere
DEFAULT_DOWNLOAD_DIR = os.environ.get(
    "DOWNLOAD_DIR",
    os.path.join("/tmp", "nexus_downloads")
    if os.name != "nt"
    else os.path.join(os.path.expanduser("~"), "Downloads"),
)

# ---------------------------------------------------------------------------
# Flask app
# ---------------------------------------------------------------------------

app = Flask(__name__)

# ── HTML page (all CSS/JS embedded) ─────────────────────────────────────────
HTML_PAGE = """<!DOCTYPE html>
<html lang="si">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Nexus Ultra Video &amp; MP3 Studio | In-App Preview &amp; Downloader</title>
    <link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800&family=Noto+Sans+Sinhala:wght@400;500;600;700;800&display=swap" rel="stylesheet">
    <style>
        :root {
            --bg: #070a14;
            --surface: rgba(15, 23, 42, 0.85);
            --surface-card: rgba(22, 32, 56, 0.72);
            --border: rgba(255, 255, 255, 0.10);
            --border-hover: rgba(99, 102, 241, 0.5);
            --primary: #6366f1;
            --primary-glow: rgba(99, 102, 241, 0.45);
            --accent: #06b6d4;
            --accent-glow: rgba(6, 182, 212, 0.45);
            --gold: #f59e0b;
            --emerald: #10b981;
            --emerald-glow: rgba(16, 185, 129, 0.4);
            --text-main: #f8fafc;
            --text-muted: #94a3b8;
        }

        * { margin: 0; padding: 0; box-sizing: border-box;
            font-family: 'Plus Jakarta Sans', 'Noto Sans Sinhala', sans-serif; }

        body {
            background-color: var(--bg);
            background-image:
                radial-gradient(circle at 15% 15%, rgba(99,102,241,0.16) 0px, transparent 40%),
                radial-gradient(circle at 85% 85%, rgba(6,182,212,0.16) 0px, transparent 45%),
                linear-gradient(rgba(255,255,255,0.02) 1px, transparent 1px),
                linear-gradient(90deg, rgba(255,255,255,0.02) 1px, transparent 1px);
            background-size: 100% 100%, 100% 100%, 32px 32px, 32px 32px;
            color: var(--text-main);
            min-height: 100vh;
            display: flex;
            flex-direction: column;
            align-items: center;
            padding: 20px 16px;
        }

        .container { width: 100%; max-width: 1140px; }

        header { text-align: center; margin-bottom: 20px; }

        .badge-pill {
            display: inline-flex; align-items: center; gap: 8px;
            background: rgba(99,102,241,0.16);
            border: 1px solid rgba(99,102,241,0.45);
            padding: 5px 16px; border-radius: 999px;
            font-size: 12px; font-weight: 700; color: #c7d2fe;
            margin-bottom: 10px; letter-spacing: 0.5px;
            box-shadow: 0 0 20px rgba(99,102,241,0.25);
        }

        h1 {
            font-size: 28px; font-weight: 800;
            background: linear-gradient(135deg, #ffffff 30%, #93c5fd 70%, #a5b4fc 100%);
            -webkit-background-clip: text; -webkit-text-fill-color: transparent;
            margin-bottom: 6px; letter-spacing: -0.5px;
        }

        .subtitle { font-size: 13.5px; color: var(--text-muted);
            max-width: 680px; margin: 0 auto; line-height: 1.5; }

        .glass-card {
            background: var(--surface);
            backdrop-filter: blur(16px); -webkit-backdrop-filter: blur(16px);
            border: 1px solid var(--border);
            border-radius: 18px; padding: 18px;
            box-shadow: 0 12px 36px rgba(0,0,0,0.55); margin-bottom: 18px;
        }

        .input-box { display: flex; gap: 10px; margin-bottom: 10px; }

        .url-field {
            flex: 1;
            background: rgba(11,16,30,0.85);
            border: 1px solid rgba(255,255,255,0.12);
            border-radius: 14px; padding: 13px 18px;
            color: #fff; font-size: 14px; outline: none;
            transition: all 0.25s ease;
        }
        .url-field:focus { border-color: var(--primary);
            box-shadow: 0 0 0 3px var(--primary-glow);
            background: rgba(11,16,30,0.98); }
        .url-field::placeholder { color: #475569; }

        button {
            border: none; border-radius: 14px; font-weight: 700;
            font-size: 13.5px; cursor: pointer;
            transition: all 0.2s cubic-bezier(0.16,1,0.3,1);
            display: inline-flex; align-items: center;
            justify-content: center; gap: 8px; user-select: none;
        }

        .btn-paste {
            background: rgba(255,255,255,0.08);
            border: 1px solid rgba(255,255,255,0.14);
            color: #e2e8f0; padding: 0 18px;
        }
        .btn-paste:hover { background: rgba(255,255,255,0.16); color: #fff; }

        .btn-analyze {
            background: linear-gradient(135deg, var(--primary) 0%, #4338ca 100%);
            color: #fff; padding: 0 24px;
            box-shadow: 0 4px 18px var(--primary-glow);
        }
        .btn-analyze:hover:not(:disabled) {
            transform: translateY(-2px);
            box-shadow: 0 6px 24px var(--primary-glow);
        }
        .btn-analyze:disabled { opacity: 0.6; cursor: not-allowed; }

        .supported-bar { display: flex; align-items: center; gap: 8px;
            flex-wrap: wrap; font-size: 12px; color: #64748b; }

        .tag-pill {
            background: rgba(255,255,255,0.04);
            border: 1px solid rgba(255,255,255,0.08);
            padding: 3px 9px; border-radius: 6px;
            color: #94a3b8; font-weight: 500;
        }

        .studio-grid {
            display: none;
            grid-template-columns: 1.15fr 0.85fr;
            gap: 18px; margin-bottom: 18px;
            animation: slideUp 0.35s cubic-bezier(0.16,1,0.3,1) forwards;
        }
        @keyframes slideUp {
            from { opacity: 0; transform: translateY(12px); }
            to   { opacity: 1; transform: translateY(0); }
        }

        .video-profile-card {
            background: rgba(8,12,22,0.7);
            border: 1px solid rgba(255,255,255,0.09);
            border-radius: 16px; padding: 14px; margin-bottom: 16px;
        }

        /* Preview Tab switcher */
        .preview-tabs { display: flex; gap: 8px; margin-bottom: 10px; }
        .preview-tab {
            flex: 1; padding: 8px 12px; border-radius: 10px;
            font-size: 12px; font-weight: 700;
            background: rgba(255,255,255,0.05);
            border: 1px solid rgba(255,255,255,0.08);
            color: #94a3b8; cursor: pointer; transition: all 0.2s ease;
        }
        .preview-tab.active {
            background: rgba(6,182,212,0.18);
            border-color: rgba(6,182,212,0.6); color: #38bdf8;
            box-shadow: 0 0 14px rgba(6,182,212,0.25);
        }

        /* 16:9 cinema box */
        .cinema-preview-box {
            position: relative; width: 100%; padding-top: 56.25%;
            border-radius: 14px; overflow: hidden; background: #000;
            border: 1px solid rgba(6,182,212,0.35);
            box-shadow: 0 8px 30px rgba(0,0,0,0.85); margin-bottom: 12px;
        }
        .preview-inner { position: absolute; top:0; left:0; width:100%; height:100%; }

        .preview-iframe { display: none; width: 100%; height: 100%; border: none; }
        .preview-video  { display: none; width: 100%; height: 100%;
            background: #000; outline: none; }
        .preview-cover  { display: block; width: 100%; height: 100%; position: relative; }
        .preview-thumb-img { width: 100%; height: 100%; object-fit: cover; }

        .play-overlay {
            position: absolute; top:0; left:0; width:100%; height:100%;
            background: linear-gradient(to top,rgba(0,0,0,0.85) 0%,rgba(0,0,0,0.2) 60%,rgba(0,0,0,0.4) 100%);
            display: flex; flex-direction: column;
            align-items: center; justify-content: center;
            cursor: pointer; transition: all 0.2s ease;
        }
        .play-overlay:hover {
            background: linear-gradient(to top,rgba(0,0,0,0.7) 0%,rgba(0,0,0,0.15) 60%,rgba(0,0,0,0.3) 100%);
        }
        .play-circle {
            width:58px; height:58px; border-radius:50%;
            background: rgba(6,182,212,0.95); color:#fff;
            display:flex; align-items:center; justify-content:center;
            font-size:22px; box-shadow:0 0 25px rgba(6,182,212,0.7);
            margin-bottom:8px; transition:transform 0.2s ease;
        }
        .play-overlay:hover .play-circle { transform:scale(1.1); background:#38bdf8; }
        .play-cta-text {
            font-size:12px; font-weight:700; color:#f8fafc;
            background:rgba(15,23,42,0.85);
            border:1px solid rgba(255,255,255,0.2);
            padding:4px 12px; border-radius:999px;
        }
        .preview-corner-badge {
            position:absolute; top:10px; left:10px;
            background:rgba(6,182,212,0.3); border:1px solid rgba(6,182,212,0.6);
            color:#38bdf8; font-size:10.5px; font-weight:800;
            padding:3px 8px; border-radius:6px;
            text-transform:uppercase; letter-spacing:0.5px;
        }
        .preview-dur-badge {
            position:absolute; bottom:10px; right:10px;
            background:rgba(0,0,0,0.85); color:#fff;
            font-size:11px; font-weight:700; padding:3px 8px;
            border-radius:6px; font-family:monospace;
        }

        .video-meta-bar { display:flex; align-items:center; gap:10px; margin-bottom:6px; }
        .platform-badge {
            background:rgba(99,102,241,0.2); border:1px solid rgba(99,102,241,0.5);
            color:#a5b4fc; font-size:11px; font-weight:800; padding:2px 8px; border-radius:6px;
        }
        .uploader-badge { color:#94a3b8; font-size:12px; font-weight:600; }
        .video-title {
            font-size:15px; font-weight:700; color:#fff; line-height:1.4;
            display:-webkit-box; -webkit-line-clamp:2;
            -webkit-box-orient:vertical; overflow:hidden;
        }

        .quality-options-title {
            font-size:13px; font-weight:700; color:#cbd5e1;
            margin-bottom:10px; display:flex;
            align-items:center; justify-content:space-between;
        }

        .quality-list {
            display:flex; flex-direction:column; gap:8px;
            max-height:380px; overflow-y:auto; padding-right:4px;
        }
        .quality-list::-webkit-scrollbar { width:6px; }
        .quality-list::-webkit-scrollbar-track { background:rgba(255,255,255,0.02); border-radius:3px; }
        .quality-list::-webkit-scrollbar-thumb { background:rgba(255,255,255,0.15); border-radius:3px; }

        .quality-card {
            background:var(--surface-card); border:1px solid var(--border);
            border-radius:12px; padding:11px 14px;
            display:flex; align-items:center; justify-content:space-between;
            cursor:pointer; transition:all 0.2s cubic-bezier(0.16,1,0.3,1); user-select:none;
        }
        .quality-card:hover { border-color:var(--border-hover); transform:translateX(3px);
            background:rgba(30,41,72,0.85); }
        .quality-card.active {
            border-color:#38bdf8; background:rgba(14,116,144,0.25);
            box-shadow:0 0 20px rgba(6,182,212,0.3);
        }

        .q-left { display:flex; align-items:center; gap:12px; }
        .q-radio {
            width:18px; height:18px; border-radius:50%;
            border:2px solid #475569; display:flex;
            align-items:center; justify-content:center; transition:all 0.2s ease;
        }
        .quality-card.active .q-radio { border-color:#38bdf8; background:#38bdf8; }
        .q-radio::after { content:''; width:6px; height:6px; border-radius:50%;
            background:#0f172a; display:none; }
        .quality-card.active .q-radio::after { display:block; }

        .q-info { display:flex; flex-direction:column; }
        .q-label-row { display:flex; align-items:center; gap:8px; }
        .q-label { font-weight:700; font-size:13.5px; color:#fff; }
        .q-badge { font-size:10px; font-weight:800; padding:2px 7px;
            border-radius:4px; letter-spacing:0.5px; }

        .badge-gold   { background:rgba(245,158,11,0.2); color:#fbbf24; border:1px solid rgba(245,158,11,0.4); }
        .badge-purple { background:rgba(168,85,247,0.2); color:#c084fc; border:1px solid rgba(168,85,247,0.4); }
        .badge-cyan   { background:rgba(6,182,212,0.2);  color:#38bdf8; border:1px solid rgba(6,182,212,0.4); }
        .badge-blue   { background:rgba(59,130,246,0.2); color:#60a5fa; border:1px solid rgba(59,130,246,0.4); }
        .badge-emerald{ background:rgba(16,185,129,0.2); color:#34d399; border:1px solid rgba(16,185,129,0.4); }
        .badge-slate  { background:rgba(100,116,139,0.2);color:#cbd5e1; border:1px solid rgba(100,116,139,0.4); }
        .badge-indigo { background:rgba(99,102,241,0.2); color:#a5b4fc; border:1px solid rgba(99,102,241,0.4); }
        .badge-gray   { background:rgba(107,114,128,0.2);color:#d1d5db; border:1px solid rgba(107,114,128,0.4); }

        .q-res { font-size:11.5px; color:#94a3b8; margin-top:2px; }
        .q-size-box { text-align:right; }
        .q-size { font-size:14px; font-weight:800; color:#38bdf8; letter-spacing:0.2px; }
        .q-time { font-size:11px; color:#64748b; }

        /* Right Inspector card */
        .inspector-card {
            background:var(--surface); backdrop-filter:blur(16px);
            border:1px solid rgba(6,182,212,0.45);
            box-shadow:0 12px 36px rgba(0,0,0,0.6), 0 0 30px rgba(6,182,212,0.15);
            border-radius:18px; padding:20px;
            display:flex; flex-direction:column; justify-content:space-between;
        }
        .inspector-header {
            display:flex; align-items:center; justify-content:space-between; margin-bottom:14px;
        }
        .inspector-title { font-size:12px; font-weight:800; color:#38bdf8;
            letter-spacing:1px; text-transform:uppercase; }
        .live-tag {
            background:rgba(6,182,212,0.18); border:1px solid rgba(6,182,212,0.45);
            color:#38bdf8; font-size:10px; font-weight:800; padding:2px 8px; border-radius:4px;
        }

        .size-hero-box {
            background:linear-gradient(145deg,rgba(8,14,28,0.95),rgba(16,26,52,0.9));
            border:1px solid rgba(6,182,212,0.5); border-radius:14px;
            padding:18px 16px; text-align:center;
            box-shadow:0 8px 24px rgba(0,0,0,0.5),inset 0 0 25px rgba(6,182,212,0.12);
            margin-bottom:16px; transition:all 0.25s ease;
        }
        .size-label-small {
            font-size:11.5px; color:#94a3b8; font-weight:600;
            text-transform:uppercase; letter-spacing:0.5px; margin-bottom:4px;
        }
        .size-hero-val {
            font-size:38px; font-weight:900; color:#38bdf8;
            letter-spacing:-0.5px; line-height:1.1;
            text-shadow:0 0 25px rgba(56,189,248,0.6);
        }
        .size-hero-sub { font-size:12px; font-weight:700; color:#a5b4fc; margin-top:4px; }

        .audio-wave { display:none; align-items:center; justify-content:center;
            gap:4px; height:24px; margin-top:8px; }
        .wave-bar { width:4px; height:100%; background:#34d399; border-radius:2px;
            animation:waveBounce 0.8s ease-in-out infinite alternate; }
        .wave-bar:nth-child(1){animation-delay:0.1s;}
        .wave-bar:nth-child(2){animation-delay:0.3s;}
        .wave-bar:nth-child(3){animation-delay:0.5s;}
        .wave-bar:nth-child(4){animation-delay:0.2s;}
        .wave-bar:nth-child(5){animation-delay:0.4s;}
        @keyframes waveBounce { from{height:4px;} to{height:22px;} }

        .spec-list { display:flex; flex-direction:column; gap:9px; margin-bottom:16px; }
        .spec-row {
            display:flex; justify-content:space-between; font-size:12.5px;
            padding:6px 10px; background:rgba(255,255,255,0.03);
            border-radius:8px; border:1px solid rgba(255,255,255,0.05);
        }
        .spec-k { color:#94a3b8; font-weight:500; }
        .spec-v { color:#f1f5f9; font-weight:700; text-align:right; }

        .dest-bar {
            display:flex; align-items:center; justify-content:space-between;
            font-size:12px; background:rgba(11,16,30,0.8);
            border:1px solid rgba(255,255,255,0.08);
            padding:8px 12px; border-radius:10px; margin-bottom:16px;
        }
        .dest-dir-text {
            color:#38bdf8; font-weight:600;
            max-width:140px; white-space:nowrap; overflow:hidden; text-overflow:ellipsis;
        }
        .btn-folder {
            background:rgba(255,255,255,0.08); border:1px solid rgba(255,255,255,0.12);
            color:#e2e8f0; font-size:11px; padding:4px 10px; border-radius:6px;
        }
        .btn-folder:hover { background:rgba(255,255,255,0.15); color:#fff; }

        .btn-download-big {
            width:100%;
            background:linear-gradient(135deg,#06b6d4 0%,#3b82f6 50%,#6366f1 100%);
            color:#fff; padding:15px; border-radius:14px;
            font-size:15px; font-weight:800; letter-spacing:0.3px;
            box-shadow:0 6px 24px rgba(6,182,212,0.45);
        }
        .btn-download-big:hover:not(:disabled) {
            transform:translateY(-2px); box-shadow:0 10px 32px rgba(6,182,212,0.6);
        }
        .btn-download-big:disabled { opacity:0.6; cursor:not-allowed; }

        .progress-hub {
            display:none; background:var(--surface);
            border:1px solid rgba(99,102,241,0.4);
            box-shadow:0 12px 36px rgba(0,0,0,0.6),0 0 25px rgba(99,102,241,0.2);
            border-radius:18px; padding:20px; margin-bottom:20px;
            animation:slideUp 0.3s ease;
        }
        .prog-header { display:flex; justify-content:space-between; align-items:center; margin-bottom:10px; }
        .prog-status { font-size:14px; font-weight:700; color:#fff;
            display:flex; align-items:center; gap:10px; }
        .prog-pct { font-size:20px; font-weight:900; color:#38bdf8; font-family:monospace; }
        .bar-shell {
            width:100%; height:12px; background:rgba(11,16,30,0.95);
            border-radius:999px; overflow:hidden;
            border:1px solid rgba(255,255,255,0.1); margin-bottom:12px; padding:2px;
        }
        .bar-core {
            width:0%; height:100%;
            background:linear-gradient(90deg,#06b6d4,#6366f1,#a855f7);
            border-radius:999px; transition:width 0.25s ease;
            box-shadow:0 0 12px rgba(6,182,212,0.6);
        }
        .prog-stats { display:flex; justify-content:space-between; font-size:13px; color:var(--text-muted); }

        .completed-card {
            display:none; background:rgba(16,185,129,0.12);
            border:1px solid rgba(16,185,129,0.4);
            border-radius:14px; padding:16px 20px;
            align-items:center; justify-content:space-between; margin-top:16px;
        }

        .spinner {
            display:inline-block; width:16px; height:16px;
            border:2px solid rgba(255,255,255,0.3); border-radius:50%;
            border-top-color:#fff; animation:spin 0.8s linear infinite;
        }
        @keyframes spin { to { transform:rotate(360deg); } }

        .error-toast {
            display:none; background:rgba(239,68,68,0.15);
            border:1px solid rgba(239,68,68,0.4); color:#fca5a5;
            padding:14px 18px; border-radius:12px;
            font-size:14px; margin-bottom:18px;
        }

        @media (max-width:860px) {
            .studio-grid { grid-template-columns:1fr; }
            .input-box { flex-direction:column; }
            .btn-paste,.btn-analyze { width:100%; padding:14px; }
        }
    </style>
</head>
<body>
<div class="container">
    <header>
        <div class="badge-pill">⚡ NEXUS VIDEO &amp; MP3 STUDIO • IN-APP VIDEO PREVIEW</div>
        <h1>වීඩියෝ සහ MP3 ඩවුන්ලෝඩරය</h1>
        <p class="subtitle">ඕනෑම වීඩියෝවක් මෙතනින්ම Preview බලා 4K, 2K, 1080p, 720p, 480p, 360p හෝ MP3 Audio බාගත කරගන්න.</p>
    </header>

    <div class="error-toast" id="errorToast"></div>

    <!-- URL Input Card -->
    <div class="glass-card">
        <div class="input-box">
            <input type="text" id="urlInput" class="url-field"
                   placeholder="වීඩියෝ ලින්ක් එක (Video Link / URL) මෙතනට Paste කරන්න..."
                   autocomplete="off">
            <button class="btn-paste" onclick="pasteClipboard()">📋 Paste</button>
            <button class="btn-analyze" id="btnAnalyze" onclick="analyzeLink()">
                <span id="analyzeSpinner" class="spinner" style="display:none;"></span>
                <span id="analyzeBtnText">⚡ පරීක්ෂා කරන්න (Analyze)</span>
            </button>
        </div>
        <div class="supported-bar">
            <span>සහය දක්වන වේදිකා:</span>
            <span class="tag-pill">YouTube (4K • In-App Preview)</span>
            <span class="tag-pill">TikTok</span>
            <span class="tag-pill">Facebook Reels</span>
            <span class="tag-pill">Instagram</span>
            <span class="tag-pill">X (Twitter)</span>
            <span class="tag-pill">Vimeo</span>
            <span class="tag-pill">+1000 තවත්</span>
        </div>
    </div>

    <!-- Dynamic Two-Column Studio Area -->
    <div class="studio-grid" id="studioGrid">

        <!-- Left Column: Video Preview & Quality Selection -->
        <div class="glass-card" style="margin-bottom:0;">
            <div class="video-profile-card">

                <!-- Tab Controls -->
                <div class="preview-tabs">
                    <button class="preview-tab active" id="tabVideo" onclick="switchPreviewTab('video')">
                        ▶ වීඩියෝව මෙතනින් නරඹන්න (Live Player)
                    </button>
                    <button class="preview-tab" id="tabCover" onclick="switchPreviewTab('cover')">
                        🖼️ කවරය (Poster Cover)
                    </button>
                </div>

                <!-- 16:9 Cinema Box -->
                <div class="cinema-preview-box" id="cinemaBox">
                    <div class="preview-inner">
                        <!-- 1. Embed iframe (YouTube / Vimeo / TikTok) -->
                        <iframe id="previewIframe" class="preview-iframe" src=""
                                allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture; web-share"
                                referrerpolicy="strict-origin-when-cross-origin"
                                allowfullscreen></iframe>

                        <!-- 2. Native HTML5 Video (direct streams) -->
                        <video id="previewVideo" class="preview-video" controls playsinline preload="metadata">
                            <source id="previewVideoSrc" src="" type="video/mp4">
                        </video>

                        <!-- 3. Thumbnail cover -->
                        <div id="previewCover" class="preview-cover">
                            <img id="previewImg" class="preview-thumb-img" src="" alt="Video Cover">
                            <div class="play-overlay" onclick="switchPreviewTab('video')">
                                <div class="play-circle">▶</div>
                                <div class="play-cta-text">වීඩියෝව මෙතනින් නරඹන්න (Play Video Inside App)</div>
                            </div>
                        </div>

                        <div class="preview-corner-badge" id="previewBadge">IN-APP PREVIEW</div>
                        <div class="preview-dur-badge" id="previewDur">Ready</div>
                    </div>
                </div>

                <div class="video-meta-bar">
                    <span class="platform-badge" id="platformBadge">WEB</span>
                    <span class="uploader-badge" id="uploaderName">Creator</span>
                </div>
                <div class="video-title" id="videoTitle">Online Video</div>
            </div>

            <div class="quality-options-title">
                <span>ගුණාත්මකභාවය තෝරන්න (Select Format):</span>
                <span style="font-size:11px;color:#38bdf8;text-transform:none;">File Size ක්ෂණිකව Highlight වේ</span>
            </div>
            <div class="quality-list" id="qualityList"></div>
        </div>

        <!-- Right Column: Inspector -->
        <div class="inspector-card">
            <div>
                <div class="inspector-header">
                    <div class="inspector-title">🎯 Selected Format Inspector</div>
                    <div class="live-tag">LIVE SPEC</div>
                </div>

                <div class="size-hero-box">
                    <div class="size-label-small">📦 ඇස්තමේන්තුගත File Size එක (File Size):</div>
                    <div class="size-hero-val" id="inspectorHeroSize">--</div>
                    <div class="size-hero-sub" id="inspectorHeroRes">Resolution: --</div>
                </div>

                <div class="audio-wave" id="audioWave">
                    <div class="wave-bar"></div><div class="wave-bar"></div>
                    <div class="wave-bar"></div><div class="wave-bar"></div>
                    <div class="wave-bar"></div>
                </div>

                <div class="spec-list">
                    <div class="spec-row">
                        <span class="spec-k">🎬 ගුණාත්මකභාවය (Quality)</span>
                        <span class="spec-v" id="specQuality">--</span>
                    </div>
                    <div class="spec-row">
                        <span class="spec-k">🎞️ Codec / Container</span>
                        <span class="spec-v" id="specCodec">--</span>
                    </div>
                    <div class="spec-row">
                        <span class="spec-k">📶 Stream Bitrate</span>
                        <span class="spec-v" id="specBitrate">--</span>
                    </div>
                    <div class="spec-row">
                        <span class="spec-k">⚡ බාගත වීමට ගතවන කාලය</span>
                        <span class="spec-v" id="specTime">--</span>
                    </div>
                </div>

                <div class="dest-bar">
                    <span style="color:#94a3b8;">📁 සුරැකෙන ස්ථානය:</span>
                    <span class="dest-dir-text" id="destDirText">Downloads</span>
                    <button class="btn-folder" onclick="openFolder()">📂 ෆෝල්ඩරය</button>
                </div>
            </div>

            <button class="btn-download-big" id="btnDownload" onclick="startDownload()">
                <span id="dlSpinner" class="spinner" style="display:none;"></span>
                <span id="dlBtnText">🚀 ඩවුන්ලෝඩ් කරන්න (Start Download)</span>
            </button>
        </div>
    </div>

    <!-- Progress Hub -->
    <div class="progress-hub" id="progressHub">
        <div class="prog-header">
            <div class="prog-status" id="progStatus">
                <span class="spinner" id="activeSpinner"></span>
                <span id="statusMessage">බාගත වෙමින් පවතී (Downloading)...</span>
            </div>
            <div class="prog-pct" id="progPct">0%</div>
        </div>
        <div class="bar-shell"><div class="bar-core" id="barCore"></div></div>
        <div class="prog-stats">
            <span id="speedMetric">වේගය: --</span>
            <span id="sizeMetric">ප්‍රමාණය: --</span>
            <span id="etaMetric">ඉතිරි කාලය: --</span>
        </div>
        <div class="completed-card" id="completedCard">
            <div>
                <div style="font-weight:800;color:#34d399;font-size:16px;">🎉 බාගත කිරීම සාර්ථකයි! (Download Completed)</div>
                <div style="font-size:13px;color:#cbd5e1;margin-top:3px;">ගොනුව Downloads ෆෝල්ඩරයේ සුරැකිණි.</div>
            </div>
            <button class="btn-analyze" style="padding:10px 18px;" onclick="openFolder()">📂 ගොනුව බලන්න</button>
        </div>
    </div>
</div>

<script>
    let currentUrl = '';
    let currentEmbedUrl = '';
    let currentStreamUrl = '';
    let currentOptions = [];
    let selectedQualityId = 'best';
    let pollTimer = null;
    let activeTab = 'video';

    function showError(msg) {
        const t = document.getElementById('errorToast');
        t.innerText = msg || '';
        t.style.display = msg ? 'block' : 'none';
    }

    async function pasteClipboard() {
        try {
            const text = await navigator.clipboard.readText();
            if (text) { document.getElementById('urlInput').value = text.trim(); analyzeLink(); }
        } catch { document.getElementById('urlInput').focus(); }
    }

    async function analyzeLink() {
        const url = document.getElementById('urlInput').value.trim();
        if (!url) { showError('කරුණාකර වලංගු වීඩියෝ ලින්ක් එකක් ඇතුළත් කරන්න.'); return; }
        showError('');
        currentUrl = url;

        const btn = document.getElementById('btnAnalyze');
        const spinner = document.getElementById('analyzeSpinner');
        const btnText = document.getElementById('analyzeBtnText');
        btn.disabled = true;
        spinner.style.display = 'inline-block';
        btnText.innerText = 'හඳුනාගනිමින් පවතී...';

        try {
            const res = await fetch('/api/info', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ url })
            });
            const data = await res.json();
            if (!res.ok || data.error) throw new Error(data.error || 'Error fetching info');

            currentOptions   = data.options  || [];
            currentEmbedUrl  = data.embed_url || '';
            currentStreamUrl = data.stream_url || '';

            document.getElementById('videoTitle').innerText   = data.title    || 'Online Video';
            document.getElementById('platformBadge').innerText= (data.platform||'WEB').toUpperCase();
            document.getElementById('uploaderName').innerText  = data.uploader || 'Creator';
            document.getElementById('previewDur').innerText   = data.duration  || 'Ready';
            document.getElementById('destDirText').innerText  = data.download_dir || 'Downloads';

            if (data.thumbnail) document.getElementById('previewImg').src = data.thumbnail;

            renderQualityList(currentOptions);
            if (currentOptions.length > 0) selectQuality(currentOptions[0].id);

            document.getElementById('studioGrid').style.display = 'grid';
            document.getElementById('progressHub').style.display = 'none';
            switchPreviewTab('video');

        } catch (err) {
            showError('දෝෂයකි: ' + err.message);
        } finally {
            btn.disabled = false;
            spinner.style.display = 'none';
            btnText.innerText = '⚡ පරීක්ෂා කරන්න (Analyze)';
        }
    }

    function switchPreviewTab(tab) {
        activeTab = tab;
        const iframe = document.getElementById('previewIframe');
        const video  = document.getElementById('previewVideo');
        const cover  = document.getElementById('previewCover');
        document.getElementById('tabVideo').classList.toggle('active', tab === 'video');
        document.getElementById('tabCover').classList.toggle('active', tab === 'cover');

        if (tab === 'video') {
            cover.style.display = 'none';
            if (currentEmbedUrl) {
                video.style.display = 'none';
                if (iframe.src !== currentEmbedUrl) iframe.src = currentEmbedUrl;
                iframe.style.display = 'block';
            } else if (currentStreamUrl) {
                iframe.style.display = 'none';
                document.getElementById('previewVideoSrc').src = currentStreamUrl;
                video.load();
                video.style.display = 'block';
                video.play().catch(() => {});
            } else {
                cover.style.display = 'block';
                iframe.style.display = 'none';
                video.style.display = 'none';
            }
        } else {
            cover.style.display = 'block';
            iframe.style.display = 'none';
            video.style.display = 'none';
            try { video.pause(); } catch {}
        }
    }

    function renderQualityList(options) {
        const list = document.getElementById('qualityList');
        list.innerHTML = '';
        options.forEach(opt => {
            const card = document.createElement('div');
            card.className = 'quality-card' + (opt.id === selectedQualityId ? ' active' : '');
            card.id = 'opt-' + opt.id;
            card.onclick = () => selectQuality(opt.id);
            card.innerHTML = `
                <div class="q-left">
                    <div class="q-radio"></div>
                    <div class="q-info">
                        <div class="q-label-row">
                            <span class="q-label">${opt.label}</span>
                            <span class="q-badge badge-${opt.badge_color||'cyan'}">${opt.badge}</span>
                        </div>
                        <span class="q-res">${opt.res_text}</span>
                    </div>
                </div>
                <div class="q-size-box">
                    <div class="q-size">${opt.size_str}</div>
                    <div class="q-time">${opt.est_time}</div>
                </div>`;
            list.appendChild(card);
        });
    }

    function selectQuality(id) {
        selectedQualityId = id;
        document.querySelectorAll('.quality-card').forEach(el => el.classList.remove('active'));
        const el = document.getElementById('opt-' + id);
        if (el) el.classList.add('active');

        const opt = currentOptions.find(o => o.id === id);
        if (!opt) return;

        const hero = document.getElementById('inspectorHeroSize');
        hero.innerText = opt.size_str;
        hero.style.transform = 'scale(1.08)';
        setTimeout(() => { hero.style.transform = 'scale(1)'; }, 150);

        document.getElementById('inspectorHeroRes').innerText = opt.res_text;
        document.getElementById('specQuality').innerText  = opt.label;
        document.getElementById('specCodec').innerText    = opt.codec;
        document.getElementById('specBitrate').innerText  = opt.bitrate;
        document.getElementById('specTime').innerText     = opt.est_time;

        const wave = document.getElementById('audioWave');
        const dlTxt = document.getElementById('dlBtnText');
        if (opt.type === 'audio') {
            wave.style.display = 'flex';
            dlTxt.innerText = '🎵 MP3 බාගත කරන්න (Download Audio)';
        } else {
            wave.style.display = 'none';
            dlTxt.innerText = '🚀 වීඩියෝව බාගත කරන්න (Start Download)';
        }
    }

    async function startDownload() {
        if (!currentUrl) return;
        const btn = document.getElementById('btnDownload');
        const spinner = document.getElementById('dlSpinner');
        const btnTxt = document.getElementById('dlBtnText');

        btn.disabled = true;
        spinner.style.display = 'inline-block';
        btnTxt.innerText = 'බාගත කිරීම ආරම්භ වේ...';

        document.getElementById('progressHub').style.display = 'block';
        document.getElementById('completedCard').style.display = 'none';
        document.getElementById('activeSpinner').style.display = 'inline-block';
        document.getElementById('barCore').style.width = '0%';
        document.getElementById('progPct').innerText = '0%';
        document.getElementById('progressHub').scrollIntoView({ behavior: 'smooth' });

        try {
            const res = await fetch('/api/download', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ url: currentUrl, quality: selectedQualityId })
            });
            const data = await res.json();
            if (!res.ok || data.error) throw new Error(data.error || 'Cannot start download');
            if (pollTimer) clearInterval(pollTimer);
            pollTimer = setInterval(pollProgress, 500);
        } catch (err) {
            showError('බාගත කිරීමේ දෝෂයකි: ' + err.message);
            btn.disabled = false;
            spinner.style.display = 'none';
            btnTxt.innerText = '🚀 ඩවුන්ලෝඩ් කරන්න (Start Download)';
        }
    }

    async function pollProgress() {
        try {
            const res = await fetch('/api/progress');
            const p = await res.json();

            if (p.status === 'downloading') {
                document.getElementById('barCore').style.width = p.percent + '%';
                document.getElementById('progPct').innerText = p.percent + '%';
                document.getElementById('statusMessage').innerText = 'බාගත වෙමින් පවතී (Downloading)...';
                document.getElementById('speedMetric').innerText = 'වේගය: ' + (p.speed || '--');
                document.getElementById('sizeMetric').innerText  = 'ප්‍රමාණය: ' + (p.size  || '--');
                document.getElementById('etaMetric').innerText   = 'ඉතිරි කාලය: ' + (p.eta  || '--');
            } else if (p.status === 'processing') {
                document.getElementById('barCore').style.width = '100%';
                document.getElementById('progPct').innerText = '100%';
                document.getElementById('statusMessage').innerText = 'ගොනුව සකසමින් (FFmpeg Merging)... ⏳';
            } else if (p.status === 'completed') {
                clearInterval(pollTimer);
                document.getElementById('barCore').style.width = '100%';
                document.getElementById('progPct').innerText = '100%';
                document.getElementById('statusMessage').innerText = 'සාර්ථකයි! 🎉';
                document.getElementById('activeSpinner').style.display = 'none';
                document.getElementById('completedCard').style.display = 'flex';
                document.getElementById('btnDownload').disabled = false;
                document.getElementById('dlSpinner').style.display = 'none';
                document.getElementById('dlBtnText').innerText = 'නැවත ඩවුන්ලෝඩ් කරන්න (Download Again)';
            } else if (p.status === 'error') {
                clearInterval(pollTimer);
                showError('දෝෂයකි: ' + p.error);
                document.getElementById('btnDownload').disabled = false;
                document.getElementById('dlSpinner').style.display = 'none';
                document.getElementById('dlBtnText').innerText = '🚀 ඩවුන්ලෝඩ් කරන්න (Start Download)';
            }
        } catch {}
    }

    async function openFolder() {
        await fetch('/api/open-folder', { method: 'POST' });
    }

    document.getElementById('urlInput').addEventListener('keypress', e => {
        if (e.key === 'Enter') analyzeLink();
    });
</script>
</body>
</html>
"""


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/")
def index():
    return Response(HTML_PAGE, mimetype="text/html; charset=utf-8")


@app.get("/api/progress")
def api_progress():
    with download_lock:
        return jsonify(current_download)


@app.post("/api/info")
def api_info():
    body = request.get_json(silent=True) or {}
    url = (body.get("url") or "").strip()
    if not url:
        return jsonify({"error": "Missing URL"}), 400
    try:
        info = downloader_core.get_video_info(url, timeout=4.0)
        info["download_dir"] = DEFAULT_DOWNLOAD_DIR
        return jsonify(info)
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@app.post("/api/download")
def api_download():
    body = request.get_json(silent=True) or {}
    url = (body.get("url") or "").strip()
    quality = body.get("quality", "best")
    if not url:
        return jsonify({"error": "Missing URL"}), 400

    def run_dl():
        with download_lock:
            current_download.update(
                status="downloading", percent=0,
                speed="", eta="", size="", error=""
            )

        def cb(p):
            with download_lock:
                current_download.update(p)

        try:
            downloader_core.download_media(url, quality, DEFAULT_DOWNLOAD_DIR, cb)
        except Exception as exc:
            with download_lock:
                current_download.update(status="error", error=str(exc))

    threading.Thread(target=run_dl, daemon=True).start()
    return jsonify({"status": "started"})


@app.post("/api/open-folder")
def api_open_folder():
    """
    On Linux/cloud: returns the path (no GUI to open).
    On Windows desktop: opens Explorer.
    """
    os.makedirs(DEFAULT_DOWNLOAD_DIR, exist_ok=True)
    if os.name == "nt":
        try:
            os.startfile(DEFAULT_DOWNLOAD_DIR)
        except Exception:
            pass
    else:
        try:
            subprocess.Popen(["xdg-open", DEFAULT_DOWNLOAD_DIR])
        except Exception:
            pass
    return jsonify({"status": "ok", "path": DEFAULT_DOWNLOAD_DIR})


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    print(f"  🎬 Nexus Video & MP3 Studio → http://0.0.0.0:{port}")
    print(f"  📁 Downloads → {DEFAULT_DOWNLOAD_DIR}")
    # debug=False, threaded=True for concurrent downloads + progress polling
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
