function showPageError(message) {
  const banner = document.querySelector("[data-testid='page-error']");
  const text = message ? String(message) : "This page hit an error.";
  if (!banner) {
    return;
  }
  banner.hidden = false;
  banner.textContent = text;
}

window.addEventListener("error", (event) => {
  showPageError(event && event.message ? event.message : "This page hit an error.");
});

window.addEventListener("unhandledrejection", (event) => {
  const reason = event && event.reason;
  showPageError(reason && reason.message ? reason.message : "This page hit an error.");
});

function listen(node, type, handler) {
  if (!node) {
    showPageError("A control on this page is missing. The version in the header is the build that is running.");
    return;
  }
  try {
    node.addEventListener(type, handler);
  } catch (error) {
    showPageError(error && error.message ? error.message : "A button could not be attached.");
  }
}

const thread = document.querySelector("#thread");
const form = document.querySelector("#composer");
const input = document.querySelector("#instruction");
const send = form ? form.querySelector("button[type='submit']") : null;
const talk = document.querySelector("[data-testid='talk']");
const mute = document.querySelector("[data-testid='mute']");
const micStatus = document.querySelector("[data-testid='mic-status']");
const desktopSwitch = document.querySelector("[data-testid='desktop-control']");
const wakeSwitch = document.querySelector("[data-testid='wake-word']");
const recordingBar = document.querySelector("[data-testid='recording']");
const recordingTimer = document.querySelector("[data-testid='recording-timer']");
const recordingStop = document.querySelector("[data-testid='recording-stop']");
const recordingCancel = document.querySelector("[data-testid='recording-cancel']");
const checkUpdates = document.querySelector("[data-testid='check-updates']");
const updateStatus = document.querySelector("[data-testid='update-status']");
const trackBranch = document.querySelector("[data-testid='track-branch']");
const trackName = document.querySelector("[data-testid='track-branch-name']");
const applyUpdate = document.querySelector("[data-testid='apply-update']");
const runtimeStatus = document.querySelector("[data-testid='runtime-status']");

const STATUS_LABELS = {
  queued: "Waiting",
  running: "Working",
  completed: "Completed",
  failed: "Failed",
  blocked: "Blocked",
  stopped: "Stopped",
  needs_human: "Needs human",
  needs_key: "Needs a key",
  needs_approval: "Needs approval",
  paused: "Paused",
};

const STEP_LABELS = {
  completed: "Completed",
  failed: "Failed",
  blocked: "Blocked",
  running: "Working",
  stopped: "Stopped",
  queued: "Waiting",
};

let pollTimer = 0;
let renderedCount = 0;
let recorder = null;
let recordStream = null;
let recordChunks = [];
let recordSeconds = 0;
let recordTick = 0;
let recognition = null;
let listening = false;
let finishing = false;
let keepListening = false;
let speechSawResult = false;
let speechWait = 0;
let recorderReady = Promise.resolve(false);
let baseText = "";
let finalText = "";
let interimText = "";
const recordingSend = document.querySelector("[data-testid='recording-send']");
const startCompanion = document.querySelector("[data-testid='start-companion']");
let wakeTimer = 0;
let voicePrimed = false;
let liveSource = null;
let liveId = "";
const reports = new Map();
const spoken = new Set();
const TERMINAL = new Set(["completed", "failed", "blocked", "stopped", "needs_human", "needs_key"]);

function formatClock(total) {
  const seconds = Math.max(0, Math.floor(Number(total) || 0));
  const minutes = Math.floor(seconds / 60);
  const rest = seconds % 60;
  return String(minutes).padStart(2, "0") + ":" + String(rest).padStart(2, "0");
}

function muted() {
  return window.localStorage.getItem("machaa-muted") === "1";
}

function setMic(text) {
  if (micStatus) {
    micStatus.textContent = text;
  }
}

listen(mute, "click", () => {
  const next = !muted();
  window.localStorage.setItem("machaa-muted", next ? "1" : "0");
  mute.setAttribute("aria-pressed", next ? "true" : "false");
  mute.textContent = next ? "Muted" : "Mute";
  if (next && window.speechSynthesis) {
    window.speechSynthesis.cancel();
  }
  if (next) {
    setMic("Muted");
    if (wakeSwitch) {
      wakeSwitch.checked = false;
    }
    window.clearTimeout(wakeTimer);
  } else {
    setMic("Microphone off");
  }
});

try {
  if (mute && muted()) {
    mute.setAttribute("aria-pressed", "true");
    mute.textContent = "Muted";
    setMic("Muted");
  }

  listen(talk, "click", () => {
    startListening();
  });

  listen(recordingStop, "click", () => {
    hideRecording();
    finishListening("stop");
  });

  listen(recordingSend, "click", () => {
    hideRecording();
    finishListening("send");
  });

  listen(recordingCancel, "click", () => {
    hideRecording();
    finishListening("cancel");
  });
} catch (error) {
  showPageError(error && error.message ? error.message : "This page could not start.");
}

function speechCtor() {
  return window.SpeechRecognition || window.webkitSpeechRecognition || null;
}

function joinSpeech(base, spoken) {
  const left = (base || "").trim();
  const right = (spoken || "").trim();
  if (!right) {
    return left;
  }
  if (!left) {
    return right;
  }
  return left + " " + right;
}

function showLive() {
  input.value = joinSpeech(baseText, finalText + interimText);
}

function clearSpeechWait() {
  window.clearTimeout(speechWait);
  speechWait = 0;
}

function speechGaveUp(reason) {
  if (speechSawResult) {
    return;
  }
  clearSpeechWait();
  keepListening = false;
  const rec = recognition;
  recognition = null;
  if (rec) {
    rec.onresult = null;
    rec.onerror = null;
    rec.onend = null;
    try {
      if (rec.abort) {
        rec.abort();
      } else {
        rec.stop();
      }
    } catch (error) {
      /* The engine had already stopped. */
    }
  }
  if (listening) {
    setMic(reason);
  }
}

function armSpeechWatch() {
  clearSpeechWait();
  speechWait = window.setTimeout(() => {
    if (!speechSawResult && listening) {
      speechGaveUp("The browser speech engine returned no words. Stop will turn the recording into text.");
    }
  }, 3000);
}

async function startListening() {
  if (listening || finishing) {
    return;
  }
  if (!window.isSecureContext) {
    setMic("Open http://127.0.0.1:8787 so the microphone can work. You can still type.");
    return;
  }
  if (muted()) {
    setMic("Muted");
    return;
  }
  baseText = input.value;
  finalText = "";
  interimText = "";
  recordChunks = [];
  speechSawResult = false;
  clearSpeechWait();
  keepListening = true;
  listening = true;
  showRecording();
  const Ctor = speechCtor();
  let speechStarted = false;
  if (Ctor) {
    speechStarted = startRecognition(Ctor);
  }
  let audioStarted = false;
  recorderReady = startRecorder().catch(() => false);
  try {
    audioStarted = await recorderReady;
  } catch (error) {
    audioStarted = false;
  }
  if (!listening) {
    return;
  }
  if (audioStarted) {
    armSpeechWatch();
  }
  if (!speechStarted && !audioStarted) {
    listening = false;
    keepListening = false;
    hideRecording();
    setMic("Microphone blocked. In Windows, choose Allow when the browser asks. You can still type.");
  }
}

function startRecognition(Ctor) {
  try {
    const rec = new Ctor();
    rec.lang = "en-IN";
    rec.interimResults = true;
    rec.continuous = true;
    rec.maxAlternatives = 1;
    rec.onresult = (event) => {
      try {
        speechSawResult = true;
        clearSpeechWait();
        let interim = "";
        const results = event && event.results ? event.results : [];
        const from = event && event.resultIndex ? event.resultIndex : 0;
        for (let index = from; index < results.length; index += 1) {
          const piece = results[index][0] ? results[index][0].transcript : "";
          if (results[index].isFinal) {
            finalText += piece;
          } else {
            interim += piece;
          }
        }
        interimText = interim;
        showLive();
      } catch (error) {
        showPageError(error && error.message ? error.message : "Speech could not be shown.");
      }
    };
    rec.onerror = (event) => {
      try {
        const code = event && event.error ? event.error : "";
        if (code === "language-not-supported" && rec.lang !== "en-US") {
          rec.lang = "en-US";
          try {
            rec.start();
          } catch (error) {
            speechGaveUp("The browser speech engine returned no words. Stop will turn the recording into text.");
          }
          return;
        }
        if (
          code === "network" ||
          code === "not-allowed" ||
          code === "service-not-allowed" ||
          code === "audio-capture"
        ) {
          speechGaveUp("The browser speech engine returned no words. Stop will turn the recording into text.");
        }
      } catch (error) {
        speechGaveUp("The browser speech engine returned no words. Stop will turn the recording into text.");
      }
    };
    rec.onend = () => {
      if (keepListening && recognition === rec) {
        try {
          rec.start();
        } catch (error) {
          keepListening = false;
        }
      }
    };
    rec.start();
    recognition = rec;
    return true;
  } catch (error) {
    recognition = null;
    return false;
  }
}

async function startRecorder() {
  if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
    return false;
  }
  try {
    recordStream = await navigator.mediaDevices.getUserMedia({ audio: true });
  } catch (error) {
    recordStream = null;
    return false;
  }
  if (!listening && !finishing) {
    recordStream.getTracks().forEach((track) => track.stop());
    recordStream = null;
    return false;
  }
  try {
    const mime = window.MediaRecorder && MediaRecorder.isTypeSupported("audio/webm") ? "audio/webm" : "";
    recorder = mime ? new MediaRecorder(recordStream, { mimeType: mime }) : new MediaRecorder(recordStream);
    recorder.addEventListener("dataavailable", (item) => {
      if (item.data && item.data.size) {
        recordChunks.push(item.data);
      }
    });
    recorder.start(1000);
  } catch (error) {
    recordStream.getTracks().forEach((track) => track.stop());
    recordStream = null;
    recorder = null;
    return false;
  }
  return true;
}

function stopRecognition() {
  keepListening = false;
  const rec = recognition;
  recognition = null;
  if (!rec) {
    return;
  }
  rec.onend = null;
  try {
    rec.stop();
  } catch (error) {
    return;
  }
}

function stopRecorder() {
  return new Promise((resolve) => {
    const mime = recorder && recorder.mimeType ? recorder.mimeType : "audio/webm";
    const finish = () => {
      const chunks = recordChunks.slice();
      if (recordStream) {
        recordStream.getTracks().forEach((track) => track.stop());
        recordStream = null;
      }
      recorder = null;
      recordChunks = [];
      resolve(chunks.length ? new Blob(chunks, { type: mime }) : null);
    };
    if (recorder && recorder.state !== "inactive") {
      recorder.addEventListener("stop", finish, { once: true });
      try {
        recorder.stop();
        return;
      } catch (error) {
        finish();
        return;
      }
    }
    finish();
  });
}

async function finishListening(mode) {
  clearSpeechWait();
  hideRecording();
  if (!listening || finishing) {
    return;
  }
  finishing = true;
  try {
    await recorderReady;
  } catch (error) {
    /* The microphone was not ready. Stop still ends the timer. */
  }
  listening = false;
  const base = baseText;
  const spoken = (finalText + interimText).trim();
  hideRecording();
  try {
    const blob = await stopRecorder();
    stopRecognition();
    if (mode === "cancel") {
      input.value = base;
      setMic("Recording cancelled. You can still type.");
      return;
    }
    let text = spoken;
    if (!text && blob) {
      setMic("Turning speech into text…");
      text = await uploadRecording([blob]);
    }
    if (!text || !String(text).trim()) {
      input.value = base;
      setMic("Machaa could not hear any words. You can still type.");
      return;
    }
    input.value = joinSpeech(base, text);
    input.focus();
    if (mode === "send") {
      setMic("Sending.");
      form.requestSubmit();
      return;
    }
    setMic("Ready to send. Edit the words if you want.");
  } catch (error) {
    input.value = base;
    hideRecording();
    setMic(error && error.message ? error.message : "Machaa could not turn that speech into text. You can still type.");
  } finally {
    hideRecording();
    finishing = false;
    listening = false;
  }
}

function showRecording() {
  recordSeconds = 0;
  if (recordingTimer) {
    recordingTimer.textContent = "00:00";
  }
  if (recordingBar) {
    recordingBar.hidden = false;
  }
  if (talk) {
    talk.dataset.recording = "true";
  }
  setMic("Recording");
  window.clearInterval(recordTick);
  recordTick = window.setInterval(() => {
    recordSeconds += 1;
    if (recordingTimer) {
      recordingTimer.textContent = formatClock(recordSeconds);
    }
  }, 1000);
}

function hideRecording() {
  clearSpeechWait();
  if (recordingBar) {
    recordingBar.hidden = true;
  }
  if (talk) {
    talk.dataset.recording = "false";
  }
  window.clearInterval(recordTick);
  if (recordingTimer) {
    recordingTimer.textContent = "00:00";
  }
}

async function uploadRecording(chunks) {
  if (!chunks.length) {
    const message = "That recording was empty. You can still type.";
    setMic(message);
    throw new Error(message);
  }
  const blob = chunks.length === 1 && chunks[0] instanceof Blob ? chunks[0] : new Blob(chunks);
  let response;
  try {
    response = await fetch("/api/voice/transcribe", { method: "POST", body: blob });
  } catch (error) {
    const message = "Machaa could not turn that speech into text. You can still type.";
    setMic(message);
    throw new Error(message);
  }
  let body = {};
  try {
    body = await response.json();
  } catch (error) {
    body = {};
  }
  if (!response.ok) {
    const message = body.detail || "Machaa could not turn that speech into text. You can still type.";
    setMic(message);
    throw new Error(message);
  }
  const text = (body.text || "").trim();
  input.value = text;
  input.focus();
  if (!text) {
    const message = "Machaa could not hear any words. You can still type.";
    setMic(message);
    throw new Error(message);
  }
  setMic("Ready to send. Edit the words if you want.");
  return text;
}

if (desktopSwitch) {
desktopSwitch.addEventListener("change", async () => {
  const response = await fetch("/api/desktop/permission", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ enabled: desktopSwitch.checked }),
  });
  if (!response.ok) {
    desktopSwitch.checked = false;
  }
});
}

listen(wakeSwitch, "change", async () => {
  if (muted()) {
    wakeSwitch.checked = false;
    setMic("Muted");
    return;
  }
  const response = await fetch("/api/voice/wake", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ enabled: wakeSwitch.checked }),
  });
  const body = await response.json();
  wakeSwitch.checked = Boolean(body.enabled);
  setMic(body.detail || "Microphone off");
  window.clearTimeout(wakeTimer);
  if (body.enabled) {
    wakeLoop();
  }
});

async function wakeLoop() {
  if (!wakeSwitch.checked || muted()) {
    return;
  }
  if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
    wakeSwitch.checked = false;
    setMic("This browser has no microphone. You can still type.");
    return;
  }
  let stream = null;
  try {
    stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    const chunks = [];
    const local = new MediaRecorder(stream);
    await new Promise((resolve) => {
      local.addEventListener("dataavailable", (item) => chunks.push(item.data));
      local.addEventListener("stop", resolve);
      local.start();
      window.setTimeout(() => {
        if (local.state !== "inactive") {
          local.stop();
        }
      }, 2500);
    });
    stream.getTracks().forEach((track) => track.stop());
    stream = null;
    if (chunks.length && wakeSwitch.checked) {
      const response = await fetch("/api/voice/transcribe", {
        method: "POST",
        body: new Blob(chunks),
      });
      if (response.ok) {
        const body = await response.json();
        const heard = (body.text || "").trim().toLowerCase();
        if (heard === "open machaa" || heard === "machaa, open machaa" || heard === "machaa open machaa") {
          input.value = "Open Machaa";
          form.requestSubmit();
        }
      }
    }
  } catch (error) {
    if (stream) {
      stream.getTracks().forEach((track) => track.stop());
    }
    wakeSwitch.checked = false;
    setMic("Microphone blocked. In Windows, choose Allow when the browser asks. You can still type.");
    await fetch("/api/voice/wake", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ enabled: false }),
    });
    return;
  }
  if (wakeSwitch.checked) {
    wakeTimer = window.setTimeout(wakeLoop, 400);
  }
}

listen(startCompanion, "click", async () => {
  const response = await fetch("/api/companion/start", { method: "POST" });
  const body = await response.json();
  const detail = body.detail || "Machaa cannot start the Companion from inside Docker.";
  if (runtimeStatus) {
    runtimeStatus.textContent = detail;
  }
  setMic(detail);
});

listen(document.querySelector("[data-testid='test-microphone']"), "click", () => {
  testMicrophone();
});

listen(form, "submit", async (event) => {
  event.preventDefault();
  if (listening) {
    await finishListening("send");
    return;
  }
  const instruction = input.value.trim();
  if (!instruction) {
    return;
  }
  send.disabled = true;
  try {
    const response = await fetch("/api/tasks", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ instruction }),
    });
    if (!response.ok) {
      throw new Error("Machaa could not start that task.");
    }
    input.value = "";
    await refresh();
  } catch (error) {
    window.alert(error.message);
  } finally {
    send.disabled = false;
    input.focus();
  }
});

listen(input, "keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    form.requestSubmit();
  }
});

document.querySelectorAll("[data-example]").forEach((button) => {
  button.addEventListener("click", () => {
    input.value = button.getAttribute("data-example");
    input.focus();
  });
});

listen(thread, "click", async (event) => {
  const stop = event.target.closest("[data-testid='stop']");
  const pause = event.target.closest("[data-testid='pause']");
  const resume = event.target.closest("[data-testid='resume']");
  const approve = event.target.closest("[data-testid='approve']");
  const reject = event.target.closest("[data-testid='reject']");
  const button = stop || pause || resume || approve || reject;
  if (!button) {
    return;
  }
  const action = stop ? "stop" : pause ? "pause" : resume ? "resume" : approve ? "approve" : "reject";
  button.disabled = true;
  await fetch(`/api/tasks/${button.getAttribute("data-id")}/${action}`, { method: "POST" });
  await refresh();
});

async function refresh() {
  const response = await fetch("/api/tasks");
  if (!response.ok) {
    return;
  }
  const payload = await response.json();
  render(payload.tasks || []);
  const tasks = payload.tasks || [];
  maybeSpeak(tasks);
  watchLive(tasks);
  const active = tasks.some(
    (task) =>
      task.status === "queued" ||
      task.status === "running" ||
      task.status === "paused" ||
      task.status === "needs_approval",
  );
  window.clearTimeout(pollTimer);
  if (active) {
    pollTimer = window.setTimeout(refresh, 1000);
  }
}

function render(tasks) {
  const grew = tasks.length > renderedCount;
  renderedCount = tasks.length;
  thread.textContent = "";
  if (tasks.length === 0) {
    thread.append(emptyState());
    return;
  }
  tasks.forEach((task) => thread.append(renderTask(task)));
  const latest = thread.lastElementChild;
  if (grew && latest) {
    latest.scrollIntoView({ block: "nearest" });
  }
}

function emptyState() {
  const section = document.createElement("section");
  section.className = "empty";
  section.id = "empty";
  const title = document.createElement("h2");
  title.textContent = "What should Machaa look up?";
  const copy = document.createElement("p");
  copy.textContent =
    "Machaa can search the web, open one public website, write a Word document, or prepare a social post. A Google robot check is left alone. Purchases, downloads, and your personal Chrome stay off limits.";
  section.append(title, copy);
  return section;
}

function renderTask(task) {
  const wrap = document.createElement("article");
  wrap.className = "task";
  wrap.dataset.testid = "task";
  wrap.dataset.taskId = task.id;

  const bubble = document.createElement("div");
  bubble.className = "bubble";
  bubble.textContent = task.instruction;

  const card = document.createElement("section");
  card.className = "card";
  card.dataset.status = task.status;

  const top = document.createElement("div");
  top.className = "card-top";
  const statusLine = document.createElement("div");
  statusLine.className = "status-line";
  const pill = document.createElement("span");
  pill.className = "pill";
  pill.dataset.testid = "task-status";
  pill.dataset.status = task.status;
  pill.textContent = STATUS_LABELS[task.status] || task.status;
  const phase = document.createElement("p");
  phase.className = "phase";
  phase.dataset.testid = "phase";
  phase.textContent = task.phase || "";
  const elapsed = document.createElement("span");
  elapsed.className = "elapsed";
  elapsed.dataset.testid = "elapsed";
  elapsed.textContent = formatClock(task.elapsed_seconds || 0);
  if (!TERMINAL.has(task.status) && task.started_at) {
    elapsed.dataset.elapsedFrom = task.started_at;
  }
  statusLine.append(pill, phase, elapsed);
  top.append(statusLine);
  const actions = document.createElement("div");
  actions.className = "card-actions";
  if (task.status === "needs_approval" && !task.stop_requested) {
    actions.append(
      controlButton("approve", "Approve", task.id),
      controlButton("reject", "Reject", task.id),
      controlButton("stop", "Stop", task.id),
    );
  } else if (task.status === "paused" && !task.stop_requested) {
    actions.append(controlButton("resume", "Resume", task.id), controlButton("stop", "Stop", task.id));
  } else if ((task.status === "running" || task.status === "queued") && !task.stop_requested) {
    actions.append(controlButton("pause", "Pause", task.id), controlButton("stop", "Stop", task.id));
  } else if (task.stop_requested && (task.status === "running" || task.status === "queued" || task.status === "paused")) {
    const stopping = document.createElement("span");
    stopping.className = "meta";
    stopping.textContent = "Stopping";
    actions.append(stopping);
  }
  if (actions.childNodes.length) {
    top.append(actions);
  }

  const summary = document.createElement("p");
  summary.className = "summary";
  summary.dataset.testid = "task-summary";
  summary.textContent =
    task.summary ||
    (task.status === "paused"
      ? "Paused."
      : task.status === "running"
        ? "Working on it."
        : "Waiting to start.");

  card.append(top, summary);

  if (task.saved_location) {
    const saved = document.createElement("p");
    saved.className = "summary";
    saved.dataset.testid = "saved-file";
    saved.textContent = task.saved_location;
    card.append(saved);
  }

  if (task.steps && task.steps.length) {
    const heading = document.createElement("h3");
    heading.className = "plan-title";
    heading.dataset.testid = "plan";
    heading.textContent = "Plan";
    const list = document.createElement("ol");
    list.className = "steps";
    task.steps.forEach((step) => {
      const item = document.createElement("li");
      if (step.status === "running") {
        item.dataset.current = "true";
      }
      const label = document.createElement("span");
      label.textContent = step.label;
      const state = document.createElement("span");
      state.dataset.testid = "step-state";
      state.dataset.status = step.status;
      state.textContent = STEP_LABELS[step.status] || step.status;
      item.append(label, state);
      if (step.detail && (step.status === "failed" || step.status === "blocked")) {
        const error = document.createElement("p");
        error.className = "step-error";
        error.dataset.testid = "step-error";
        error.textContent = step.detail;
        item.append(error);
      }
      list.append(item);
    });
    card.append(heading, list);
  }

  const href = safeUrl(task.page_url);
  if (href) {
    const link = document.createElement("a");
    link.className = "page-link";
    link.href = href;
    link.rel = "noreferrer noopener";
    link.target = "_blank";
    link.textContent = href;
    card.append(link);
  }

  if (task.has_screenshot) {
    const figure = document.createElement("figure");
    figure.className = "shot";
    const image = document.createElement("img");
    image.dataset.testid = "screenshot";
    image.alt = "Screenshot of the page Machaa opened";
    image.src = `/api/tasks/${task.id}/screenshot`;
    figure.append(image);
    card.append(figure);
  }

  if (task.has_document) {
    const download = document.createElement("a");
    download.className = "download";
    download.dataset.testid = "document";
    download.href = `/api/tasks/${task.id}/document`;
    download.textContent = "Download the Word document";
    card.append(download);
  }

  if (task.has_report) {
    const details = document.createElement("details");
    details.className = "report";
    details.open = true;
    const title = document.createElement("summary");
    title.textContent = "Research report";
    const pre = document.createElement("pre");
    pre.dataset.testid = "report";
    pre.textContent = reports.get(task.id) || "Loading the report…";
    details.append(title, pre);
    card.append(details);
    if (!reports.has(task.id)) {
      loadReport(task.id, pre);
    }
  }

  wrap.append(bubble, card);
  return wrap;
}

async function loadReport(id, node) {
  const response = await fetch(`/api/tasks/${id}/report`);
  if (!response.ok) {
    node.textContent = "The report is not available.";
    return;
  }
  const text = await response.text();
  reports.set(id, text);
  node.textContent = text;
}

function watchLive(tasks) {
  const active = tasks.find(
    (task) =>
      task.status === "queued" ||
      task.status === "running" ||
      task.status === "paused" ||
      task.status === "needs_approval",
  );
  if (!active) {
    if (liveSource) {
      liveSource.close();
      liveSource = null;
    }
    liveId = "";
    return;
  }
  if (liveId === active.id && liveSource) {
    return;
  }
  if (liveSource) {
    liveSource.close();
  }
  liveId = active.id;
  if (!window.EventSource) {
    return;
  }
  liveSource = new EventSource("/api/tasks/" + active.id + "/events");
  liveSource.onmessage = (event) => {
    let body = {};
    try {
      body = JSON.parse(event.data);
    } catch (error) {
      return;
    }
    const card = thread.querySelector('[data-task-id="' + active.id + '"]');
    if (!card) {
      return;
    }
    const phaseNode = card.querySelector("[data-testid='phase']");
    if (phaseNode && body.phase) {
      phaseNode.textContent = body.phase;
    }
    const elapsedNode = card.querySelector("[data-testid='elapsed']");
    if (elapsedNode && body.elapsed_seconds != null && !elapsedNode.dataset.elapsedFrom) {
      elapsedNode.textContent = formatClock(body.elapsed_seconds);
    }
  };
}

window.setInterval(() => {
  document.querySelectorAll("[data-elapsed-from]").forEach((node) => {
    const started = Date.parse(node.getAttribute("data-elapsed-from"));
    if (!Number.isFinite(started)) {
      return;
    }
    node.textContent = formatClock((Date.now() - started) / 1000);
  });
}, 1000);

function controlButton(kind, label, id) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = kind === "approve" ? "talk" : "stop";
  button.dataset.testid = kind;
  button.dataset.id = id;
  button.textContent = label;
  return button;
}

function maybeSpeak(tasks) {
  if (!voicePrimed) {
    tasks.forEach((task) => {
      if (TERMINAL.has(task.status)) {
        spoken.add(task.id);
      }
    });
    voicePrimed = true;
    return;
  }
  tasks.forEach((task) => {
    if (!TERMINAL.has(task.status) || spoken.has(task.id) || muted()) {
      return;
    }
    spoken.add(task.id);
    if (!window.speechSynthesis || !task.summary) {
      return;
    }
    window.speechSynthesis.cancel();
    const utterance = new SpeechSynthesisUtterance(task.summary);
    utterance.lang = "en-US";
    window.speechSynthesis.speak(utterance);
  });
}

function safeUrl(value) {
  if (!value) {
    return "";
  }
  try {
    const parsed = new URL(value);
    if (parsed.protocol === "https:" || parsed.protocol === "http:") {
      return parsed.href;
    }
  } catch (error) {
    return "";
  }
  return "";
}

listen(checkUpdates, "click", async () => {
  await saveTrackBranch();
  await loadUpdateStatus();
});

listen(trackBranch, "change", saveTrackBranch);

listen(applyUpdate, "click", async () => {
  applyUpdate.disabled = true;
  try {
    const response = await fetch("/api/updates/apply", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ approved: true }),
    });
    const body = await response.json();
    updateStatus.textContent = body.detail || "The update was not applied.";
    if (response.ok) {
      applyUpdate.hidden = true;
    }
  } catch (error) {
    updateStatus.textContent = "The update was not applied. Your files were left as they were.";
  } finally {
    applyUpdate.disabled = false;
  }
});

async function saveTrackBranch() {
  const response = await fetch("/api/updates/track", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      enabled: trackBranch.checked,
      branch: trackName.value.trim(),
    }),
  });
  const body = await response.json();
  trackBranch.checked = Boolean(body.enabled);
  if (!body.enabled) {
    trackName.value = "";
  }
  if (body.detail) {
    updateStatus.textContent = body.detail;
  }
}

async function loadUpdateStatus() {
  const response = await fetch("/api/updates");
  if (!response.ok) {
    updateStatus.textContent = "Machaa could not check for updates.";
    return;
  }
  const body = await response.json();
  const track = body.track || {};
  trackBranch.checked = Boolean(track.enabled);
  trackName.value = track.branch || "";
  const available = body.available ? " Available: " + (body.version || body.ref) + "." : "";
  updateStatus.textContent = "Current version " + (body.current || "") + ". " + (body.detail || "") + available;
  applyUpdate.hidden = !body.available;
}

function showRuntime(health) {
  if (!runtimeStatus) {
    return;
  }
  const parts = [];
  if (health.reconnect) {
    parts.push(health.reconnect);
  } else {
    if (health.docker === "running") {
      parts.push("Docker is running.");
    }
    if (health.companion_status === "reachable") {
      parts.push("Companion is running.");
    } else if (health.companion_status === "not_running") {
      parts.push("Companion is not running.");
    }
  }
  parts.push(health.browser_worker === "busy" ? "Browser is busy." : "Browser is ready.");
  runtimeStatus.textContent = parts.join(" ");
}

async function loadSetup() {
  const banner = document.querySelector("[data-testid='gemini-setup']");
  try {
    const response = await fetch("/api/health");
    if (!response.ok) {
      return;
    }
    const health = await response.json();
    if (health.gemini_configured && banner) {
      banner.hidden = true;
    }
    if (desktopSwitch) {
      desktopSwitch.checked = Boolean(health.desktop_enabled);
    }
    if (wakeSwitch) {
      wakeSwitch.checked = false;
    }
    showRuntime(health);
    if (health.wake_enabled) {
      await fetch("/api/voice/wake", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ enabled: false }),
      });
    }
    await loadUpdateStatus();
  } catch (error) {
    if (banner) {
      banner.hidden = false;
    }
    if (runtimeStatus) {
      runtimeStatus.textContent = "Machaa is not connected. Double-click START-MACHAA.bat and leave that window open.";
    }
  }
}

async function testMicrophone() {
  const diagnostic = document.querySelector("[data-testid='mic-diagnostic']");
  const lines = [];
  const label = document.querySelector("[data-testid='build-label']");
  if (label && label.textContent) {
    lines.push("Build " + label.textContent.trim() + ".");
  }
  lines.push(
    window.isSecureContext
      ? "This page is a secure context, so the microphone is allowed to run."
      : "This page is not a secure context. Open http://127.0.0.1:8787.",
  );
  lines.push(
    speechCtor()
      ? "Speech engine: this browser can type words as you talk."
      : "Speech engine: this browser has no speech engine. A recording will be sent for transcription.",
  );
  if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
    lines.push("Mic level: blocked. In Windows, choose Allow when the browser asks.");
  } else {
    let stream = null;
    let audioContext = null;
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      audioContext = new AudioContext();
      if (audioContext.state === "suspended") {
        await audioContext.resume();
      }
      const source = audioContext.createMediaStreamSource(stream);
      const analyser = audioContext.createAnalyser();
      analyser.fftSize = 256;
      source.connect(analyser);
      const data = new Uint8Array(analyser.fftSize);
      await new Promise((resolve) => window.setTimeout(resolve, 400));
      analyser.getByteTimeDomainData(data);
      let sum = 0;
      for (let index = 0; index < data.length; index += 1) {
        const centered = (data[index] - 128) / 128;
        sum += centered * centered;
      }
      const level = Math.sqrt(sum / data.length);
      lines.push(
        level > 0.02
          ? "Mic level: hearing sound."
          : "Mic level: quiet. Speak, or check that Windows allows this browser to use the microphone.",
      );
    } catch (error) {
      lines.push("Mic level: blocked. In Windows, choose Allow when the browser asks.");
    } finally {
      if (stream) {
        stream.getTracks().forEach((track) => track.stop());
      }
      if (audioContext) {
        try {
          await audioContext.close();
        } catch (error) {
          /* The audio context was already closed. */
        }
      }
    }
  }
  if (diagnostic) {
    diagnostic.hidden = false;
    diagnostic.textContent = lines.join(" ");
  }
  setMic(lines[lines.length - 1]);
}

try {
  loadSetup();
  refresh();
} catch (error) {
  showPageError(error && error.message ? error.message : "This page could not start.");
}
