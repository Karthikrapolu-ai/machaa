const thread = document.querySelector("#thread");
const form = document.querySelector("#composer");
const input = document.querySelector("#instruction");
const send = form.querySelector("button[type='submit']");
const talk = document.querySelector("[data-testid='talk']");
const mute = document.querySelector("[data-testid='mute']");
const micStatus = document.querySelector("[data-testid='mic-status']");
const desktopSwitch = document.querySelector("[data-testid='desktop-control']");
const wakeSwitch = document.querySelector("[data-testid='wake-word']");

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
let wakeTimer = 0;
let voicePrimed = false;
const reports = new Map();
const spoken = new Set();
const TERMINAL = new Set(["completed", "failed", "blocked", "stopped", "needs_human", "needs_key"]);

function muted() {
  return window.localStorage.getItem("machaa-muted") === "1";
}

function setMic(text) {
  micStatus.textContent = text;
}

mute.addEventListener("click", () => {
  const next = !muted();
  window.localStorage.setItem("machaa-muted", next ? "1" : "0");
  mute.setAttribute("aria-pressed", next ? "true" : "false");
  mute.textContent = next ? "Muted" : "Mute";
  if (next && window.speechSynthesis) {
    window.speechSynthesis.cancel();
  }
  if (next) {
    setMic("Muted");
    wakeSwitch.checked = false;
    window.clearTimeout(wakeTimer);
  } else {
    setMic("Microphone off");
  }
});

if (muted()) {
  mute.setAttribute("aria-pressed", "true");
  mute.textContent = "Muted";
  setMic("Muted");
}

talk.addEventListener("pointerdown", async (event) => {
  event.preventDefault();
  if (muted()) {
    setMic("Muted");
    return;
  }
  if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
    setMic("This browser has no microphone. You can still type.");
    return;
  }
  try {
    recordStream = await navigator.mediaDevices.getUserMedia({ audio: true });
  } catch (error) {
    setMic("Microphone blocked. In Windows, choose Allow when the browser asks. You can still type.");
    return;
  }
  const chunks = [];
  recorder = new MediaRecorder(recordStream);
  recorder.addEventListener("dataavailable", (item) => {
    if (item.data && item.data.size) {
      chunks.push(item.data);
    }
  });
  recorder.addEventListener("stop", () => uploadRecording(chunks));
  recorder.start();
  setMic("Listening");
  talk.setPointerCapture(event.pointerId);
});

talk.addEventListener("pointerup", stopTalk);
talk.addEventListener("pointercancel", stopTalk);

function stopTalk() {
  if (recorder && recorder.state !== "inactive") {
    recorder.stop();
  }
  recorder = null;
  if (recordStream) {
    recordStream.getTracks().forEach((track) => track.stop());
    recordStream = null;
  }
  if (!muted()) {
    setMic("Microphone off");
  }
}

async function uploadRecording(chunks) {
  if (!chunks.length) {
    setMic("That recording was empty. You can still type.");
    return;
  }
  const blob = new Blob(chunks);
  try {
    const response = await fetch("/api/voice/transcribe", { method: "POST", body: blob });
    const body = await response.json();
    if (!response.ok) {
      setMic(body.detail || "Voice typing is unavailable. You can still type.");
      return;
    }
    input.value = body.text || "";
    if (input.value.trim()) {
      form.requestSubmit();
    }
  } catch (error) {
    setMic("Voice typing is unavailable. You can still type.");
  }
}

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

wakeSwitch.addEventListener("change", async () => {
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

form.addEventListener("submit", async (event) => {
  event.preventDefault();
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

input.addEventListener("keydown", (event) => {
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

thread.addEventListener("click", async (event) => {
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
  const pill = document.createElement("span");
  pill.className = "pill";
  pill.dataset.testid = "task-status";
  pill.dataset.status = task.status;
  pill.textContent = STATUS_LABELS[task.status] || task.status;
  top.append(pill);
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

  if (task.steps && task.steps.length) {
    const heading = document.createElement("h3");
    heading.className = "plan-title";
    heading.dataset.testid = "plan";
    heading.textContent = "Plan";
    const list = document.createElement("ol");
    list.className = "steps";
    task.steps.forEach((step) => {
      const item = document.createElement("li");
      const label = document.createElement("span");
      label.textContent = step.label;
      const state = document.createElement("span");
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

async function loadSetup() {
  const banner = document.querySelector("[data-testid='gemini-setup']");
  try {
    const response = await fetch("/api/health");
    if (!response.ok) {
      return;
    }
    const health = await response.json();
    if (health.gemini_configured) {
      banner.hidden = true;
    }
    desktopSwitch.checked = Boolean(health.desktop_enabled);
    wakeSwitch.checked = false;
    if (health.wake_enabled) {
      await fetch("/api/voice/wake", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ enabled: false }),
      });
    }
  } catch (error) {
    banner.hidden = false;
  }
}

loadSetup();
refresh();
