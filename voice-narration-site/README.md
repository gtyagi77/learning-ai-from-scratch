# VoiceForge — Self-Hosted Voice Cloning & Script Narration

Clone a voice, paste a script, and download the narration as an audio file —
running **entirely on your own machine**. There is no third-party API: the
browser talks only to a small local server, and the actual voice cloning is
done by the open-source [**Chatterbox TTS**](https://github.com/resemble-ai/chatterbox)
model (Resemble AI, MIT-licensed). No audio, script, or key ever leaves your computer.

## Architecture

```
┌─────────────┐   HTTP (localhost only)   ┌──────────────────────────────┐
│  Browser UI │ ────────────────────────► │  FastAPI server (server/)    │
│  web/       │   POST /api/voices        │   • stores voice samples      │
│             │   POST /api/narrate       │   • Chatterbox TTS  (engine)  │
└─────────────┘ ◄──────────────────────── │   • ffmpeg for decode/encode │
     audio blob / mp3                      └──────────────────────────────┘
```

- **`web/`** — static frontend (HTML/CSS/JS), served by the same server.
- **`server/main.py`** — FastAPI app: voice CRUD, script chunking, WAV stitching, MP3 export.
- **`server/engine.py`** — thin wrapper around Chatterbox; loads the model locally
  and generates speech in the cloned voice.

The model runs locally on **CPU, CUDA, or Apple MPS** — auto-detected, or forced
with `VOICEFORGE_DEVICE`.

## Quick start

```bash
cd voice-narration-site
./run.sh                 # creates a venv, installs deps, starts the server
# open http://127.0.0.1:8080
```

`run.sh` downloads PyTorch on first run; the Chatterbox weights (~2 GB) download
the first time you generate audio. Installing **ffmpeg** is recommended — it
enables MP3/M4A/WebM samples, in-browser mic recording, and MP3 output. Without
it, only `.wav` samples work and output is WAV.

### Try the UI without the model

To develop or demo the interface without downloading multi-GB weights, run in
placeholder mode — it generates simple tones instead of real speech:

```bash
VOICEFORGE_FAKE_TTS=1 ./run.sh
```

## How to use

1. **Create a voice clone** — record 10–30 seconds with your mic, or upload audio
   files. Name the voice, tick the consent box, and click *Save voice clone*.
   Saved voices persist under `server/data/voices/` and appear in the dropdown.
2. **Generate** — paste your script, optionally adjust the expressiveness / pacing
   sliders, and click *Generate narration*. Long scripts are split on sentence
   boundaries and stitched into one file.
3. **Download** — play it in the page or download the MP3 (or WAV without ffmpeg).

No model loaded yet? The *Quick preview* button reads your script with the
browser's built-in voice (generic, no cloning) so you can sanity-check the text.

## API

| Method | Endpoint | Purpose |
|---|---|---|
| `GET` | `/api/health` | Engine status, device, ffmpeg availability |
| `GET` | `/api/voices` | List saved voices |
| `POST` | `/api/voices` | Create a voice from uploaded sample(s) (`multipart/form-data`) |
| `DELETE` | `/api/voices/{id}` | Delete a saved voice |
| `POST` | `/api/narrate` | Generate narration audio for a script in a chosen voice |

## Configuration

| Env var | Default | Meaning |
|---|---|---|
| `PORT` | `8080` | Server port |
| `VOICEFORGE_DEVICE` | auto | Force `cpu`, `cuda`, or `mps` |
| `VOICEFORGE_FAKE_TTS` | unset | `1` = placeholder tones, no model download |

## Responsible use

Only clone voices you own or have the speaker's explicit permission to use. The
UI requires a consent confirmation before cloning. Impersonating someone without
consent may be illegal in your jurisdiction.

## Files

| Path | Purpose |
|---|---|
| `web/index.html` · `styles.css` · `app.js` | Frontend UI |
| `server/main.py` | FastAPI backend + static hosting |
| `server/engine.py` | Local Chatterbox TTS wrapper |
| `server/requirements.txt` | Python dependencies |
| `run.sh` | One-command setup + launch |
