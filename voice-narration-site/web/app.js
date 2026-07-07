/* VoiceForge — self-hosted voice cloning + script narration.
 * The browser talks only to this site's own local backend (/api/*),
 * which runs the open-source Chatterbox TTS model. Nothing is sent to
 * any third-party service. */

const MAX_UPLOAD_FILES = 10;

const state = {
  voices: [],
  selectedVoiceId: null,
  recordedBlob: null,
  uploadedFiles: [],
  recorder: null,
  recordTimerId: null,
};

const $ = (id) => document.getElementById(id);

/* ---------- helpers ---------- */

function setStatus(el, msg, kind) {
  el.textContent = msg;
  el.className = "status" + (kind ? " " + kind : "");
}

async function apiError(res) {
  try {
    const body = await res.json();
    return body?.detail ? (typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail)) : res.statusText;
  } catch (_) {
    return `${res.status} ${res.statusText}`;
  }
}

/* ---------- engine health ---------- */

async function checkEngine() {
  const badge = $("engine-badge");
  try {
    const res = await fetch("/api/health");
    if (!res.ok) throw new Error();
    const info = await res.json();
    if (info.loaded) {
      badge.textContent = `● Engine ready — ${info.engine} on ${info.device}`;
      badge.className = "engine-badge ok";
    } else {
      badge.textContent = `○ Engine: ${info.engine} (loads on first generation)`;
      badge.className = "engine-badge idle";
    }
  } catch (_) {
    badge.textContent = "✕ Local backend not reachable — start the server (see README).";
    badge.className = "engine-badge err";
  }
}

/* ---------- voices ---------- */

async function loadVoices() {
  try {
    const res = await fetch("/api/voices");
    if (!res.ok) throw new Error(await apiError(res));
    state.voices = (await res.json()).voices || [];
    renderVoices();
  } catch (err) {
    setStatus($("clone-status"), `Could not load voices: ${err.message}`, "err");
  }
}

function renderVoices() {
  const sel = $("voice-select");
  sel.innerHTML = "";
  const placeholder = document.createElement("option");
  placeholder.value = "";
  placeholder.textContent = state.voices.length ? "— choose a voice —" : "No voices yet — create one above";
  sel.appendChild(placeholder);
  for (const v of state.voices) {
    const opt = document.createElement("option");
    opt.value = v.voice_id;
    opt.textContent = v.name;
    sel.appendChild(opt);
  }
  if (state.selectedVoiceId && state.voices.some((v) => v.voice_id === state.selectedVoiceId)) {
    sel.value = state.selectedVoiceId;
  } else {
    state.selectedVoiceId = null;
  }
  $("btn-delete-voice").disabled = !state.selectedVoiceId;
  refreshButtons();
}

async function deleteVoice() {
  if (!state.selectedVoiceId) return;
  const name = state.voices.find((v) => v.voice_id === state.selectedVoiceId)?.name || "this voice";
  if (!confirm(`Delete "${name}"? This removes its stored sample.`)) return;
  try {
    const res = await fetch(`/api/voices/${state.selectedVoiceId}`, { method: "DELETE" });
    if (!res.ok) throw new Error(await apiError(res));
    state.selectedVoiceId = null;
    await loadVoices();
    setStatus($("clone-status"), "Voice deleted.", "ok");
  } catch (err) {
    setStatus($("clone-status"), `Delete failed: ${err.message}`, "err");
  }
}

/* ---------- record / upload ---------- */

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
  if (state.recordedBlob) form.append("files", state.recordedBlob, "recorded-sample.webm");
  for (const f of state.uploadedFiles) form.append("files", f, f.name);

  $("btn-clone").disabled = true;
  setStatus(status, "Saving voice sample…", "busy");
  try {
    const res = await fetch("/api/voices", { method: "POST", body: form });
    if (!res.ok) throw new Error(await apiError(res));
    const data = await res.json();
    state.selectedVoiceId = data.voice_id;
    await loadVoices();
    setStatus(status, `✔ Voice "${name}" saved and selected. Head to step 2!`, "ok");
  } catch (err) {
    setStatus(status, `Saving failed: ${err.message}`, "err");
  } finally {
    refreshButtons();
  }
}

/* ---------- generate narration ---------- */

function splitPreview(text) {
  const sentences = text.match(/[^.!?\n]+[.!?\n]*/g) || [text];
  let chunks = 0, len = 0;
  for (const s of sentences) {
    if (len && len + s.length > 300) { chunks += 1; len = 0; }
    len += s.length;
  }
  if (len) chunks += 1;
  return chunks;
}

function updateScriptMeta() {
  const text = $("script").value;
  $("char-count").textContent = `${text.length} characters`;
  const n = text.trim() ? splitPreview(text) : 0;
  $("chunk-count").textContent = n > 1 ? `~${n} chunks (stitched automatically)` : "";
}

async function generateNarration() {
  const text = $("script").value.trim();
  const status = $("generate-status");
  if (!text) { setStatus(status, "Write a script first.", "err"); return; }
  if (!state.selectedVoiceId) { setStatus(status, "Create or select a voice in step 1 first.", "err"); return; }

  $("btn-generate").disabled = true;
  $("result").hidden = true;
  $("progress").hidden = false;
  setStatus(status, "Generating narration locally… this can take a while on CPU.", "busy");

  try {
    const res = await fetch("/api/narrate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        voice_id: state.selectedVoiceId,
        text,
        exaggeration: parseFloat($("exaggeration").value),
        cfg_weight: parseFloat($("cfg").value),
      }),
    });
    if (!res.ok) throw new Error(await apiError(res));

    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    $("result-audio").src = url;

    const disp = res.headers.get("Content-Disposition") || "";
    const match = disp.match(/filename="?([^"]+)"?/);
    const ext = blob.type.includes("mpeg") ? "mp3" : "wav";
    const dl = $("btn-download");
    dl.href = url;
    dl.download = match ? match[1] : `narration.${ext}`;

    $("result").hidden = false;
    setStatus(status, `✔ Done — ${(blob.size / 1024 / 1024).toFixed(2)} MB generated locally.`, "ok");
  } catch (err) {
    setStatus(status, `Generation failed: ${err.message}`, "err");
  } finally {
    $("progress").hidden = true;
    refreshButtons();
  }
}

/* ---------- browser-voice quick preview ---------- */

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
    $("btn-preview").textContent = "▶ Quick preview (browser voice, no cloning)";
    return;
  }
  const u = new SpeechSynthesisUtterance(text);
  u.onend = () => { $("btn-preview").textContent = "▶ Quick preview (browser voice, no cloning)"; };
  speechSynthesis.speak(u);
  $("btn-preview").textContent = "■ Stop preview";
  setStatus(status, "Playing a generic browser voice — use Generate for the cloned narration.", "busy");
}

/* ---------- wiring ---------- */

function refreshButtons() {
  const hasSample = !!state.recordedBlob || state.uploadedFiles.length > 0;
  $("btn-clone").disabled = !(hasSample && $("consent").checked && $("voice-name").value.trim());
  $("btn-generate").disabled = !state.selectedVoiceId;
  $("btn-delete-voice").disabled = !state.selectedVoiceId;
}

function init() {
  $("btn-record").addEventListener("click", toggleRecording);
  $("file-upload").addEventListener("change", handleUpload);
  $("consent").addEventListener("change", refreshButtons);
  $("voice-name").addEventListener("input", refreshButtons);
  $("btn-clone").addEventListener("click", createClone);
  $("btn-refresh-voices").addEventListener("click", loadVoices);
  $("btn-delete-voice").addEventListener("click", deleteVoice);
  $("voice-select").addEventListener("change", (e) => {
    state.selectedVoiceId = e.target.value || null;
    refreshButtons();
  });
  $("script").addEventListener("input", updateScriptMeta);
  $("exaggeration").addEventListener("input", (e) => { $("exaggeration-val").textContent = (+e.target.value).toFixed(2); });
  $("cfg").addEventListener("input", (e) => { $("cfg-val").textContent = (+e.target.value).toFixed(2); });
  $("btn-generate").addEventListener("click", generateNarration);
  $("btn-preview").addEventListener("click", previewWithBrowserVoice);

  updateScriptMeta();
  refreshButtons();
  checkEngine();
  loadVoices();
}

document.addEventListener("DOMContentLoaded", init);
