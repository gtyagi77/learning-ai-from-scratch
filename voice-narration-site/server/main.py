"""VoiceForge local backend — self-hosted voice cloning and narration.

FastAPI server that stores voice samples on disk, clones voices with the
open-source Chatterbox TTS model, and renders narration audio. It also serves
the static frontend from ../web, so one process runs the whole site:

    uvicorn server.main:app --host 127.0.0.1 --port 8080

No third-party API is involved; nothing leaves this machine.
"""

import json
import re
import shutil
import subprocess
import time
import uuid
import wave
from pathlib import Path

import anyio
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .engine import TTSEngine

BASE = Path(__file__).resolve().parent
WEB_DIR = BASE.parent / "web"
VOICES_DIR = BASE / "data" / "voices"
NARRATIONS_DIR = BASE / "data" / "narrations"
VOICES_DIR.mkdir(parents=True, exist_ok=True)
NARRATIONS_DIR.mkdir(parents=True, exist_ok=True)

MAX_CHUNK_CHARS = 300  # Chatterbox performs best on short passages
SAMPLE_RATE = 24000
FFMPEG = shutil.which("ffmpeg")

engine = TTSEngine()
app = FastAPI(title="VoiceForge local backend")


# ---------- audio helpers ----------

def to_wav(src: Path, dst: Path):
    """Normalize any uploaded/recorded audio to 24 kHz mono 16-bit WAV."""
    if FFMPEG:
        proc = subprocess.run(
            [FFMPEG, "-y", "-i", str(src), "-ar", str(SAMPLE_RATE), "-ac", "1",
             "-sample_fmt", "s16", str(dst)],
            capture_output=True, text=True,
        )
        if proc.returncode != 0:
            raise HTTPException(400, f"Could not decode audio file: {proc.stderr[-300:]}")
        return
    # No ffmpeg: accept WAV files as-is, reject formats we can't decode.
    if src.suffix.lower() == ".wav":
        shutil.copy(src, dst)
        return
    raise HTTPException(
        400,
        "ffmpeg is not installed, so only .wav uploads are supported. "
        "Install ffmpeg to use MP3/M4A/WebM samples or in-browser recording.",
    )


def concat_wavs(parts, dst: Path):
    """Join WAVs that share sample params (they do — to_wav normalized them)."""
    with wave.open(str(dst), "wb") as out:
        for i, part in enumerate(parts):
            with wave.open(str(part), "rb") as w:
                if i == 0:
                    out.setparams(w.getparams())
                out.writeframes(w.readframes(w.getnframes()))


def split_script(text: str):
    """Sentence-aware split into chunks the model handles well."""
    sentences = re.findall(r"[^.!?\n]+[.!?\n]*", text) or [text]
    chunks, current = [], ""
    for s in sentences:
        if current and len(current) + len(s) > MAX_CHUNK_CHARS:
            chunks.append(current)
            current = ""
        if len(s) > MAX_CHUNK_CHARS:
            for i in range(0, len(s), MAX_CHUNK_CHARS):
                chunks.append(s[i:i + MAX_CHUNK_CHARS])
        else:
            current += s
    if current.strip():
        chunks.append(current)
    return [c.strip() for c in chunks if c.strip()]


# ---------- API ----------

@app.get("/api/health")
def health():
    info = engine.describe()
    info.update({"status": "ok", "ffmpeg": bool(FFMPEG)})
    return info


@app.get("/api/voices")
def list_voices():
    voices = []
    for meta_path in sorted(VOICES_DIR.glob("*/meta.json")):
        try:
            voices.append(json.loads(meta_path.read_text()))
        except (json.JSONDecodeError, OSError):
            continue
    return {"voices": voices}


@app.post("/api/voices")
async def create_voice(name: str = Form(...), files: list[UploadFile] = File(...)):
    name = name.strip()
    if not name:
        raise HTTPException(400, "Voice name is required.")
    if not files:
        raise HTTPException(400, "At least one audio sample is required.")

    voice_id = uuid.uuid4().hex[:12]
    vdir = VOICES_DIR / voice_id
    vdir.mkdir(parents=True)
    try:
        parts = []
        for i, upload in enumerate(files[:10]):
            raw = vdir / f"raw-{i}{Path(upload.filename or 'sample').suffix or '.bin'}"
            raw.write_bytes(await upload.read())
            part = vdir / f"part-{i}.wav"
            to_wav(raw, part)
            raw.unlink()
            parts.append(part)
        concat_wavs(parts, vdir / "sample.wav")
        for p in parts:
            p.unlink()
    except Exception:
        shutil.rmtree(vdir, ignore_errors=True)
        raise

    meta = {"voice_id": voice_id, "name": name, "created": int(time.time())}
    (vdir / "meta.json").write_text(json.dumps(meta))
    return meta


@app.delete("/api/voices/{voice_id}")
def delete_voice(voice_id: str):
    vdir = VOICES_DIR / voice_id
    if not (vdir / "meta.json").exists():
        raise HTTPException(404, "Voice not found.")
    shutil.rmtree(vdir)
    return {"deleted": voice_id}


class NarrateRequest(BaseModel):
    voice_id: str
    text: str
    exaggeration: float = Field(0.5, ge=0.0, le=1.0)
    cfg_weight: float = Field(0.5, ge=0.0, le=1.0)


@app.post("/api/narrate")
async def narrate(req: NarrateRequest):
    text = req.text.strip()
    if not text:
        raise HTTPException(400, "Script text is empty.")
    sample = VOICES_DIR / req.voice_id / "sample.wav"
    meta_path = VOICES_DIR / req.voice_id / "meta.json"
    if not sample.exists():
        raise HTTPException(404, "Voice not found — create or select one first.")

    chunks = split_script(text)
    out_wav = NARRATIONS_DIR / f"{uuid.uuid4().hex[:12]}.wav"

    # Generation is CPU/GPU-heavy and slow; run it off the event loop.
    def run():
        engine.synthesize_to_wav(chunks, sample, out_wav,
                                 exaggeration=req.exaggeration,
                                 cfg_weight=req.cfg_weight)
    try:
        await anyio.to_thread.run_sync(run)
    except HTTPException:
        raise
    except Exception as exc:  # surface model errors to the UI
        raise HTTPException(500, f"Generation failed: {exc}") from exc

    voice_name = "narration"
    try:
        voice_name = json.loads(meta_path.read_text())["name"]
    except (OSError, KeyError, json.JSONDecodeError):
        pass
    safe = re.sub(r"[^\w-]+", "_", voice_name)
    stamp = time.strftime("%Y-%m-%d")

    # Prefer MP3 when ffmpeg is available; fall back to WAV.
    if FFMPEG:
        out_mp3 = out_wav.with_suffix(".mp3")
        proc = subprocess.run(
            [FFMPEG, "-y", "-i", str(out_wav), "-b:a", "160k", str(out_mp3)],
            capture_output=True,
        )
        if proc.returncode == 0:
            out_wav.unlink()
            return FileResponse(out_mp3, media_type="audio/mpeg",
                                filename=f"{safe}-{stamp}.mp3")
    return FileResponse(out_wav, media_type="audio/wav",
                        filename=f"{safe}-{stamp}.wav")


# Static frontend (registered last so /api/* wins).
app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web")
