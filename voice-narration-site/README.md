# VoiceForge — Voice Cloning & Script Narration Site

A single-page static site that lets you:

1. **Clone a voice** — record a sample with your microphone (or upload audio files) and create an instant voice clone.
2. **Narrate a script** — paste any script and generate narration in the cloned voice.
3. **Download the result** — get the finished narration as a single MP3 file.

Voice cloning and text-to-speech run on the [ElevenLabs API](https://elevenlabs.io/docs/api-reference)
using **your own API key**, entered in the browser. The key is sent only to
`api.elevenlabs.io` — there is no backend, nothing else ever sees it.

## Running it

It's a plain static site — no build step, no dependencies:

```bash
cd voice-narration-site
python3 -m http.server 8080
# open http://localhost:8080
```

> Microphone recording requires a secure context: `http://localhost` works,
> but if you host it elsewhere it must be served over HTTPS.

## How to use

1. **Connect** — paste your ElevenLabs API key (create one at elevenlabs.io → Profile → API keys).
   Voice cloning requires a plan that includes Instant Voice Cloning.
2. **Create a clone** — record 1–3 minutes of clear speech, or upload existing audio files,
   name the voice, tick the consent box, and click *Create voice clone*.
   You can also pick any voice already on your account.
3. **Generate** — paste your script, tweak stability/similarity if you like, and click
   *Generate narration*. Long scripts are split on sentence boundaries into ≤4500-character
   chunks and stitched into one MP3 automatically.
4. **Download** — play the result in the page or download the MP3.

No API key? The *Preview with browser voice* button reads your script aloud using the
browser's built-in speech synthesis (generic voice, no download).

## Features

- 🎙 In-browser microphone recording with live timer and playback preview
- 📁 Multi-file audio upload (MP3/WAV/M4A/WebM)
- ✂️ Automatic sentence-aware chunking for long scripts, with progress bar
- 🎚 Stability & similarity voice-setting sliders
- 🔑 Optional "remember key on this device" (localStorage only)
- 🆓 Free browser-voice preview fallback

## Responsible use

Only clone voices you own or have the speaker's explicit permission to use.
The site requires a consent confirmation before cloning, and impersonating
someone without consent may be illegal in your jurisdiction.

## Files

| File | Purpose |
|---|---|
| `index.html` | Page structure — the three-step flow |
| `styles.css` | Dark-theme styling |
| `app.js` | Recording, ElevenLabs API calls, chunking, stitching, download |
