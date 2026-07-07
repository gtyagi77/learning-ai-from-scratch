"""TTS engine wrapper around Chatterbox (open-source, MIT-licensed voice cloning).

Everything runs locally — no third-party API is ever called. Model weights are
downloaded once from Hugging Face on first load and cached on disk.

Set VOICEFORGE_FAKE_TTS=1 to run without the model (generates placeholder
tones); useful for developing the web UI on a machine without the weights.
"""

import hashlib
import math
import os
import struct
import wave
from pathlib import Path


class TTSEngine:
    def __init__(self):
        self.fake = os.environ.get("VOICEFORGE_FAKE_TTS") == "1"
        self.model = None
        self.device = None
        self.sr = 24000

    @property
    def loaded(self) -> bool:
        return self.fake or self.model is not None

    def describe(self) -> dict:
        return {
            "engine": "fake (placeholder tones)" if self.fake else "chatterbox-tts",
            "loaded": self.loaded,
            "device": "none" if self.fake else (self.device or "not loaded yet"),
        }

    def load(self):
        """Load the model. First call downloads ~2 GB of weights to the HF cache."""
        if self.loaded:
            return
        import torch
        from chatterbox.tts import ChatterboxTTS

        device = os.environ.get("VOICEFORGE_DEVICE")
        if not device:
            if torch.cuda.is_available():
                device = "cuda"
            elif getattr(torch.backends, "mps", None) and torch.backends.mps.is_available():
                device = "mps"
            else:
                device = "cpu"
        self.model = ChatterboxTTS.from_pretrained(device=device)
        self.device = device
        self.sr = self.model.sr

    def synthesize_to_wav(self, chunks, sample_path: Path, out_path: Path,
                          exaggeration: float = 0.5, cfg_weight: float = 0.5):
        """Generate speech for each text chunk in the cloned voice and write one WAV."""
        if self.fake:
            self._fake_synthesize(chunks, out_path)
            return
        import torch
        import torchaudio

        self.load()
        waves = []
        for chunk in chunks:
            wav = self.model.generate(
                chunk,
                audio_prompt_path=str(sample_path),
                exaggeration=exaggeration,
                cfg_weight=cfg_weight,
            )
            waves.append(wav)
        torchaudio.save(str(out_path), torch.cat(waves, dim=-1).cpu(), self.sr)

    def _fake_synthesize(self, chunks, out_path: Path):
        """Placeholder audio: one short tone per chunk, pitch derived from the text."""
        sr = self.sr
        frames = bytearray()
        for chunk in chunks:
            pitch = 220 + (int(hashlib.md5(chunk.encode()).hexdigest(), 16) % 220)
            seconds = min(2.0, 0.3 + len(chunk) / 400)
            n = int(sr * seconds)
            for i in range(n):
                fade = min(1.0, i / 500, (n - i) / 500)
                sample = int(12000 * fade * math.sin(2 * math.pi * pitch * i / sr))
                frames += struct.pack("<h", sample)
            frames += b"\x00\x00" * int(sr * 0.15)  # gap between chunks
        with wave.open(str(out_path), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(sr)
            w.writeframes(bytes(frames))
