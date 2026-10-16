const thread = document.querySelector("#thread");
const form = document.querySelector("#composer");
const input = document.querySelector("#instruction");
const send = form.querySelector("button[type='submit']");

const STATUS_LABELS = {
  queued: "Waiting",
  running: "Working",
  completed: "Completed",
  failed: "Failed",
  blocked: "Blocked",
  stopped: "Stopped",
};

let pollTimer = 0;
let renderedCount = 0;
const reports = new Map();

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
  const button = event.target.closest("[data-testid='stop']");
  if (!button) {
    return;
  }
  button.disabled = true;
  await fetch(`/api/tasks/${button.getAttribute("data-id")}/stop`, { method: "POST" });
  await refresh();
});

async function refresh() {
  const response = await fetch("/api/tasks");
  if (!response.ok) {
    return;
  }
  const payload = await response.json();
  render(payload.tasks || []);
  const active = (payload.tasks || []).some(
    (task) => task.status === "queued" || task.status === "running",
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
    "Day 1 searches Google or opens one public website, then saves a short report and a screenshot. It will not buy anything, download a file, or touch your personal Chrome.";
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
  if ((task.status === "running" || task.status === "queued") && !task.stop_requested) {
    const stop = document.createElement("button");
    stop.type = "button";
    stop.className = "stop";
    stop.dataset.testid = "stop";
    stop.dataset.id = task.id;
    stop.textContent = "Stop";
    top.append(stop);
  } else if (task.stop_requested && (task.status === "running" || task.status === "queued")) {
    const stopping = document.createElement("span");
    stopping.className = "meta";
    stopping.textContent = "Stopping";
    top.append(stopping);
  }

  const summary = document.createElement("p");
  summary.className = "summary";
  summary.dataset.testid = "task-summary";
  summary.textContent = task.summary || (task.status === "running" ? "Working on it." : "Waiting to start.");

  card.append(top, summary);

  if (task.steps && task.steps.length) {
    const list = document.createElement("ol");
    list.className = "steps";
    task.steps.forEach((step) => {
      const item = document.createElement("li");
      const label = document.createElement("span");
      label.textContent = step.label;
      const state = document.createElement("span");
      state.textContent = step.status;
      item.append(label, state);
      list.append(item);
    });
    card.append(list);
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

refresh();
