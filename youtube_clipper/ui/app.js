const state = {
  jobId: null,
  pollTimer: null,
  ready: false,
  running: false,
};

const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => [...document.querySelectorAll(selector)];

const elements = {
  form: $("#clipForm"),
  url: $("#youtubeUrl"),
  urlField: $("#urlField"),
  urlError: $("#urlError"),
  speed: $("#speedSelect"),
  quality: $("#qualitySelect"),
  startButton: $("#startButton"),
  startButtonLabel: $("#startButtonLabel"),
  healthPill: $("#healthPill"),
  healthLabel: $("#healthLabel"),
  workspace: $("#workspace"),
  workspaceLabel: $("#workspaceLabel"),
  workspaceTitle: $("#workspaceTitle"),
  progressNumber: $("#progressNumber"),
  progressBar: $("#progressBar"),
  currentStage: $("#currentStage"),
  processingLayout: $("#processingLayout"),
  errorPanel: $("#errorPanel"),
  errorMessage: $("#errorMessage"),
  resultsPanel: $("#resultsPanel"),
  clipGrid: $("#clipGrid"),
  eventList: $("#eventList"),
  systemNotice: $("#systemNotice"),
  systemMessage: $("#systemMessage"),
  performanceNotice: $("#performanceNotice"),
  performanceMessage: $("#performanceMessage"),
  stageHint: $("#stageHint"),
};

async function request(path, options = {}) {
  const response = await fetch(path, options);
  let data;
  try {
    data = await response.json();
  } catch {
    data = { error: "The local server returned an unreadable response" };
  }
  if (!response.ok) throw new Error(data.error || data.message || "Something went wrong");
  return data;
}

async function checkHealth() {
  elements.healthPill.className = "health-pill is-checking";
  elements.healthLabel.textContent = "Checking";
  try {
    const health = await request("/api/health");
    elements.healthPill.className = "health-pill is-ready";
    elements.healthLabel.textContent = "Ready";
    state.ready = true;
    elements.systemNotice.classList.add("is-hidden");
    const warnings = health.warnings || [];
    elements.performanceMessage.textContent = warnings.join(" ");
    elements.performanceNotice.classList.toggle("is-hidden", warnings.length === 0);
    $("#versionBadge").textContent = `v${health.version}`;
    $("#footerVersion").textContent = `v${health.version}`;
    elements.healthPill.title = `Ollama models: ${health.models.join(", ")}`;
    setRunning(state.running);
  } catch (error) {
    elements.healthPill.className = "health-pill is-error";
    elements.healthLabel.textContent = "Setup needed";
    elements.healthPill.title = error.message;
    state.ready = false;
    elements.systemMessage.textContent = error.message;
    elements.systemNotice.classList.remove("is-hidden");
    elements.performanceNotice.classList.add("is-hidden");
    setRunning(state.running);
  }
}

function setUrlError(message = "") {
  elements.urlError.textContent = message;
  elements.urlField.classList.toggle("has-error", Boolean(message));
}

function validUrl(value) {
  try {
    const parsed = new URL(value);
    return (parsed.protocol === "http:" || parsed.protocol === "https:") &&
      (parsed.hostname === "youtu.be" || parsed.hostname === "youtube.com" || parsed.hostname.endsWith(".youtube.com"));
  } catch {
    return false;
  }
}

function setRunning(running) {
  state.running = running;
  elements.startButton.disabled = running || !state.ready;
  elements.startButtonLabel.textContent = running
    ? "Working…"
    : state.ready
      ? "Create clips"
      : "Setup needed";
}

async function startJob(event) {
  event.preventDefault();
  const url = elements.url.value.trim();
  if (!validUrl(url)) {
    setUrlError("Paste a valid YouTube video link");
    elements.url.focus();
    return;
  }
  setUrlError();
  setRunning(true);
  resetWorkspace();
  elements.workspace.classList.remove("is-hidden");
  elements.workspace.scrollIntoView({ behavior: "smooth", block: "start" });
  try {
    const job = await request("/api/jobs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        url,
        speed: Number(elements.speed.value),
        whisper_model: elements.quality.value,
      }),
    });
    state.jobId = job.id;
    window.localStorage.setItem("localcutJobId", job.id);
    window.history.replaceState({}, "", `/?job=${job.id}`);
    renderJob(job);
    schedulePoll();
  } catch (error) {
    renderFailure(error.message);
    setRunning(false);
  }
}

function schedulePoll() {
  window.clearTimeout(state.pollTimer);
  state.pollTimer = window.setTimeout(pollJob, 1100);
}

async function pollJob() {
  if (!state.jobId) return;
  try {
    const job = await request(`/api/jobs/${state.jobId}`);
    renderJob(job);
    if (job.status === "queued" || job.status === "running") schedulePoll();
    else setRunning(false);
  } catch (error) {
    renderFailure(error.message);
    setRunning(false);
  }
}

function renderJob(job) {
  const progress = Math.max(0, Math.min(100, job.progress || 0));
  elements.progressNumber.textContent = `${progress}%`;
  elements.progressBar.style.width = `${progress}%`;
  elements.currentStage.textContent = job.stage;
  renderStageHint(job);
  renderStages(progress);
  renderEvents(job.events || []);

  if (job.status === "failed") renderFailure(job.error || "The local pipeline stopped");
  if (job.status === "completed") renderResults(job.clips || []);
}

function renderStageHint(job) {
  if (!job.created_at) return;
  const elapsedSeconds = Math.max(0, Math.floor((Date.now() - Date.parse(job.created_at)) / 1000));
  const minutes = Math.floor(elapsedSeconds / 60);
  const seconds = String(elapsedSeconds % 60).padStart(2, "0");
  let note = "Working locally.";
  if (job.progress >= 30 && job.progress < 56) {
    note = "Transcription can take a while.";
  } else if (job.progress >= 56 && job.progress < 68) {
    note = "Reading the video frame by frame.";
  } else if (job.progress >= 86 && job.progress < 100) {
    note = "Encoding each clip.";
  }
  elements.stageHint.textContent = `${note} Elapsed: ${minutes}:${seconds}.`;
}

function renderStages(progress) {
  const items = $$("#stageList li");
  items.forEach((item, index) => {
    const threshold = Number(item.dataset.threshold);
    const next = items[index + 1] ? Number(items[index + 1].dataset.threshold) : 101;
    item.classList.toggle("is-done", progress >= next || progress === 100);
    item.classList.toggle("is-active", progress >= threshold && progress < next);
  });
}

function renderEvents(events) {
  elements.eventList.replaceChildren();
  events.forEach((event) => {
    const item = document.createElement("li");
    const time = new Date(event.time).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
    item.textContent = `${time} — ${event.stage} (${event.progress}%)`;
    elements.eventList.append(item);
  });
}

function renderFailure(message) {
  elements.processingLayout.classList.add("is-hidden");
  elements.resultsPanel.classList.add("is-hidden");
  elements.errorPanel.classList.remove("is-hidden");
  elements.workspaceLabel.textContent = "Stopped";
  elements.workspaceTitle.textContent = "Couldn’t finish";
  elements.errorMessage.textContent = message;
}

function renderResults(clips) {
  elements.processingLayout.classList.add("is-hidden");
  elements.errorPanel.classList.add("is-hidden");
  elements.resultsPanel.classList.remove("is-hidden");
  elements.workspaceLabel.textContent = "Complete";
  elements.workspaceTitle.textContent = `${clips.length} topic clip${clips.length === 1 ? "" : "s"} created`;
  elements.clipGrid.replaceChildren();
  clips.forEach((clip, index) => elements.clipGrid.append(createClipCard(clip, index)));
}

function createClipCard(clip, index) {
  const card = document.createElement("article");
  card.className = "clip-card";
  const preview = document.createElement("div");
  preview.className = "clip-preview";
  const video = document.createElement("video");
  video.src = clip.url;
  video.controls = true;
  video.preload = "metadata";
  video.playsInline = true;
  preview.append(video);

  const meta = document.createElement("div");
  meta.className = "clip-meta";
  const name = document.createElement("div");
  name.className = "clip-name";
  const strong = document.createElement("strong");
  strong.textContent = `Clip ${index + 1}`;
  const filename = document.createElement("span");
  filename.textContent = clip.name;
  name.append(strong, filename);

  const download = document.createElement("a");
  download.className = "download-button";
  download.href = clip.url;
  download.download = clip.name;
  download.title = `Download ${clip.name}`;
  download.setAttribute("aria-label", `Download ${clip.name}`);
  download.innerHTML = '<svg viewBox="0 0 20 20" aria-hidden="true"><path d="M9.2 2h1.6v8.1l2.7-2.7 1.1 1.1-4.6 4.6-4.6-4.6 1.1-1.1 2.7 2.7V2ZM3 14h1.6v2h10.8v-2H17v3.6H3V14Z"/></svg>';
  meta.append(name, download);
  card.append(preview, meta);
  return card;
}

function resetWorkspace() {
  elements.processingLayout.classList.remove("is-hidden");
  elements.errorPanel.classList.add("is-hidden");
  elements.resultsPanel.classList.add("is-hidden");
  elements.workspaceLabel.textContent = "Working";
  elements.workspaceTitle.textContent = "Creating clips";
  elements.progressNumber.textContent = "0%";
  elements.progressBar.style.width = "0%";
  elements.currentStage.textContent = "Starting local pipeline";
  elements.stageHint.textContent = "Keep this page open.";
  elements.eventList.replaceChildren();
  renderStages(0);
}

async function restoreJob() {
  const query = new URLSearchParams(window.location.search);
  const jobId = query.get("job") || window.localStorage.getItem("localcutJobId");
  if (!jobId || !/^[a-f0-9]{12}$/.test(jobId)) return;
  state.jobId = jobId;
  try {
    const job = await request(`/api/jobs/${jobId}`);
    elements.workspace.classList.remove("is-hidden");
    renderJob(job);
    if (job.status === "queued" || job.status === "running") {
      setRunning(true);
      schedulePoll();
    }
  } catch {
    state.jobId = null;
    window.localStorage.removeItem("localcutJobId");
    window.history.replaceState({}, "", "/");
  }
}

$("#pasteButton").addEventListener("click", async () => {
  try {
    elements.url.value = await navigator.clipboard.readText();
    setUrlError();
    elements.url.focus();
  } catch {
    elements.url.focus();
  }
});

elements.url.addEventListener("input", () => setUrlError());
elements.form.addEventListener("submit", startJob);
elements.healthPill.addEventListener("click", checkHealth);
$("#tryAgainButton").addEventListener("click", () => {
  state.jobId = null;
  window.localStorage.removeItem("localcutJobId");
  window.history.replaceState({}, "", "/");
  elements.workspace.classList.add("is-hidden");
  elements.url.focus();
});

checkHealth();
restoreJob();
