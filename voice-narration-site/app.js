/* VoiceForge — voice cloning + script narration.
 * All API calls go directly from the browser to api.elevenlabs.io;
 * the key never touches any other server. */

const API_BASE = "https://api.elevenlabs.io/v1";
const TTS_MODEL = "eleven_multilingual_v2";
const MAX_CHUNK_CHARS = 4500; // stay under the per-request text limit
const MAX_UPLOAD_FILES = 10;

const state = {
  apiKey: null,
  voices: [],
  selectedVoiceId: null,
  recordedBlob: null,
  uploadedFiles: [],
  recorder: null,
  recordTimerId: null,
};

const $ = (id) => document.getElementById(id);

/* ---------- status helpers ---------- */

function setStatus(el, msg, kind) {
  el.textContent = msg;
  el.className = "status" + (kind ? " " + kind : "");
}

async function apiError(res) {
  let detail = res.statusText;
  try {
    const body = await res.json();
    detail = body?.detail?.message || body?.detail?.status || JSON.stringify(body.detail) || detail;
  } catch (_) { /* non-JSON body */ }
  return `${res.status}: ${detail}`;
}

/* ---------- Step 1: connect ---------- */

async function connect() {
  const key = $("api-key").value.trim();
  if (!key) {
    setStatus($("key-status"), "Enter your API key first.", "err");
    return;
  }
  setStatus($("key-status"), "Checking key…", "busy");
  try {
    const res = await fetch(`${API_BASE}/voices`, { headers: { "xi-api-key": key } });
    if (!res.ok) throw new Error(await apiError(res));
    const data = await res.json();
    state.apiKey = key;
    state.voices = data.voices || [];
    if ($("remember-key").checked) localStorage.setItem("vf_api_key", key);
    else localStorage.removeItem("vf_api_key");
    renderVoices();
    setStatus($("key-status"), `Connected — ${state.voices.length} voice(s) available.`, "ok");
    refreshButtons();
  } catch (err) {
    state.apiKey = null;
    setStatus($("key-status"), `Could not connect (${err.message})`, "err");
    refreshButtons();
  }
}

function renderVoices() {
  const sel = $("voice-select");
  sel.innerHTML = "";
  const placeholder = document.createElement("option");
  placeholder.value = "";
  placeholder.textContent = state.voices.length
    ? "— choose a voice —"
    : "No voices on this account yet";
  sel.appendChild(placeholder);

  // Cloned voices first, then premade.
  const sorted = [...state.voices].sort((a, b) =>
    (a.category === "cloned" ? 0 : 1) - (b.category === "cloned" ? 0 : 1));
  for (const v of sorted) {
    const opt = document.createElement("option");
    opt.value = v.voice_id;
    opt.textContent = `${v.name}${v.category === "cloned" ? " (cloned)" : ""}`;
    sel.appendChild(opt);
  }
  sel.disabled = false;
  $("btn-refresh-voices").disabled = false;
  if (state.selectedVoiceId) sel.value = state.selectedVoiceId;
}

/* ---------- Step 2: record / upload / clone ---------- */

function fmtTime(secs) {
  return `${Math.floor(secs / 60)}:${String(secs % 60).padStart(2, "0")}`;
}

async function toggleRecording() {
  const btn = $("btn-record");
  if (state.recorder && state.recorder.state === "recording") {
    state.recorder.stop();
    return;
  }
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    const chunks = [];
    const rec = new MediaRecorder(stream);
    state.recorder = rec;
    rec.ondataavailable = (e) => chunks.push(e.data);
    rec.onstop = () => {
      clearInterval(state.recordTimerId);
      stream.getTracks().forEach((t) => t.stop());
      state.recordedBlob = new Blob(chunks, { type: rec.mimeType || "audio/webm" });
      const preview = $("record-preview");
      preview.src = URL.createObjectURL(state.recordedBlob);
      preview.hidden = false;
      btn.textContent = "● Re-record";
      btn.classList.remove("recording");
      setStatus($("clone-status"), `Recorded ${(state.recordedBlob.size / 1024).toFixed(0)} KB sample.`, "ok");
      refreshButtons();
    };
    rec.start();
    let secs = 0;
    $("record-timer").textContent = fmtTime(0);
    state.recordTimerId = setInterval(() => {
      secs += 1;
      $("record-timer").textContent = fmtTime(secs);
    }, 1000);
    btn.textContent = "■ Stop recording";
    btn.classList.add("recording");
    setStatus($("clone-status"), "Recording… speak naturally.", "busy");
  } catch (err) {
    setStatus($("clone-status"), `Microphone unavailable: ${err.message}`, "err");
  }
}

function handleUpload(e) {
  state.uploadedFiles = [...e.target.files].slice(0, MAX_UPLOAD_FILES);
  const list = $("file-list");
  list.innerHTML = "";
  for (const f of state.uploadedFiles) {
    const li = document.createElement("li");
    li.textContent = `🎵 ${f.name} (${(f.size / 1024 / 1024).toFixed(1)} MB)`;
    list.appendChild(li);
  }
  refreshButtons();
}

async function createClone() {
  const name = $("voice-name").value.trim();
  const status = $("clone-status");
  if (!name) { setStatus(status, "Give the voice a name first.", "err"); return; }

  const form = new FormData();
  form.append("name", name);
  form.append("description", "Created with VoiceForge narration site");
  if (state.recordedBlob) form.append("files", state.recordedBlob, "recorded-sample.webm");
  for (const f of state.uploadedFiles) form.append("files", f, f.name);

  $("btn-clone").disabled = true;
  setStatus(status, "Uploading sample and creating clone… (can take ~30s)", "busy");
  try {
    const res = await fetch(`${API_BASE}/voices/add`, {
      method: "POST",
      headers: { "xi-api-key": state.apiKey },
      body: form,
    });
    if (!res.ok) throw new Error(await apiError(res));
    const data = await res.json();
    state.selectedVoiceId = data.voice_id;
    setStatus(status, `✔ Voice "${name}" cloned and selected. Head to step 3!`, "ok");
    await refreshVoiceList();
  } catch (err) {
    setStatus(status, `Cloning failed (${err.message})`, "err");
  } finally {
    refreshButtons();
  }
}

async function refreshVoiceList() {
  if (!state.apiKey) return;
  try {
    const res = await fetch(`${API_BASE}/voices`, { headers: { "xi-api-key": state.apiKey } });
    if (res.ok) {
      state.voices = (await res.json()).voices || [];
      renderVoices();
    }
  } catch (_) { /* keep the stale list */ }
}

/* ---------- Step 3: generate narration ---------- */

function splitScript(text) {
  // Split on sentence boundaries, packing sentences into <= MAX_CHUNK_CHARS chunks.
  const sentences = text.match(/[^.!?\n]+[.!?\n]*/g) || [text];
  const chunks = [];
  let current = "";
  for (const s of sentences) {
    if (current.length + s.length > MAX_CHUNK_CHARS && current) {
      chunks.push(current);
      current = "";
    }
    // A single sentence longer than the limit gets hard-split.
    if (s.length > MAX_CHUNK_CHARS) {
      for (let i = 0; i < s.length; i += MAX_CHUNK_CHARS) {
        chunks.push(s.slice(i, i + MAX_CHUNK_CHARS));
      }
    } else {
      current += s;
    }
  }
  if (current.trim()) chunks.push(current);
  return chunks.map((c) => c.trim()).filter(Boolean);
}

function updateScriptMeta() {
  const text = $("script").value;
  $("char-count").textContent = `${text.length} characters`;
  const n = text.trim() ? splitScript(text).length : 0;
  $("chunk-count").textContent = n > 1 ? `${n} chunks (stitched automatically)` : "";
}

async function generateNarration() {
  const text = $("script").value.trim();
  const status = $("generate-status");
  if (!text) { setStatus(status, "Write a script first.", "err"); return; }
  const voiceId = state.selectedVoiceId;
  if (!voiceId) { setStatus(status, "Create or select a voice in step 2 first.", "err"); return; }

  const chunks = splitScript(text);
  const settings = {
    stability: parseFloat($("stability").value),
    similarity_boost: parseFloat($("similarity").value),
  };

  $("btn-generate").disabled = true;
  $("result").hidden = true;
  $("progress").hidden = false;
  $("progress-bar").style.width = "0%";

  const audioParts = [];
  try {
    for (let i = 0; i < chunks.length; i++) {
      setStatus(status, `Generating audio… chunk ${i + 1} of ${chunks.length}`, "busy");
      const res = await fetch(`${API_BASE}/text-to-speech/${voiceId}`, {
        method: "POST",
        headers: {
          "xi-api-key": state.apiKey,
          "Content-Type": "application/json",
          "Accept": "audio/mpeg",
        },
        body: JSON.stringify({
          text: chunks[i],
          model_id: TTS_MODEL,
          voice_settings: settings,
        }),
      });
      if (!res.ok) throw new Error(await apiError(res));
      audioParts.push(await res.blob());
      $("progress-bar").style.width = `${((i + 1) / chunks.length) * 100}%`;
    }

    const finalBlob = new Blob(audioParts, { type: "audio/mpeg" });
    const url = URL.createObjectURL(finalBlob);
    $("result-audio").src = url;

    const voiceName = state.voices.find((v) => v.voice_id === voiceId)?.name || "narration";
    const stamp = new Date().toISOString().slice(0, 10);
    const dl = $("btn-download");
    dl.href = url;
    dl.download = `${voiceName.replace(/[^\w-]+/g, "_")}-${stamp}.mp3`;

    $("result").hidden = false;
    setStatus(status, `✔ Done — ${(finalBlob.size / 1024 / 1024).toFixed(2)} MB of audio generated.`, "ok");
  } catch (err) {
    setStatus(status, `Generation failed (${err.message})`, "err");
  } finally {
    $("progress").hidden = true;
    refreshButtons();
  }
}

/* ---------- Free preview with the browser's built-in voices ---------- */

let previewUtterance = null;

function previewWithBrowserVoice() {
  const status = $("generate-status");
  const text = $("script").value.trim();
  if (!text) { setStatus(status, "Write a script first.", "err"); return; }
  if (!("speechSynthesis" in window)) {
    setStatus(status, "This browser doesn't support speech synthesis.", "err");
    return;
  }
  if (speechSynthesis.speaking) {
    speechSynthesis.cancel();
    $("btn-preview").textContent = "▶ Preview with browser voice (free, no cloning)";
    return;
  }
  previewUtterance = new SpeechSynthesisUtterance(text);
  previewUtterance.onend = () => {
    $("btn-preview").textContent = "▶ Preview with browser voice (free, no cloning)";
  };
  speechSynthesis.speak(previewUtterance);
  $("btn-preview").textContent = "■ Stop preview";
  setStatus(status, "Playing with a generic browser voice — connect an API key for cloned narration + download.", "busy");
}

/* ---------- wiring ---------- */

function refreshButtons() {
  const hasSample = !!state.recordedBlob || state.uploadedFiles.length > 0;
  $("btn-clone").disabled = !(state.apiKey && hasSample && $("consent").checked);
  $("btn-generate").disabled = !(state.apiKey && state.selectedVoiceId);
}

function init() {
  const saved = localStorage.getItem("vf_api_key");
  if (saved) {
    $("api-key").value = saved;
    $("remember-key").checked = true;
  }

  $("btn-connect").addEventListener("click", connect);
  $("api-key").addEventListener("keydown", (e) => { if (e.key === "Enter") connect(); });
  $("btn-record").addEventListener("click", toggleRecording);
  $("file-upload").addEventListener("change", handleUpload);
  $("consent").addEventListener("change", refreshButtons);
  $("voice-name").addEventListener("input", refreshButtons);
  $("btn-clone").addEventListener("click", createClone);
  $("btn-refresh-voices").addEventListener("click", refreshVoiceList);
  $("voice-select").addEventListener("change", (e) => {
    state.selectedVoiceId = e.target.value || null;
    refreshButtons();
  });
  $("script").addEventListener("input", updateScriptMeta);
  $("stability").addEventListener("input", (e) => { $("stability-val").textContent = (+e.target.value).toFixed(2); });
  $("similarity").addEventListener("input", (e) => { $("similarity-val").textContent = (+e.target.value).toFixed(2); });
  $("btn-generate").addEventListener("click", generateNarration);
  $("btn-preview").addEventListener("click", previewWithBrowserVoice);

  updateScriptMeta();
  refreshButtons();
}

document.addEventListener("DOMContentLoaded", init);
