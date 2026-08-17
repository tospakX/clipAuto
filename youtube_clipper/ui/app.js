const state = {
  pollTimer: null,
  ready: false,
  submitting: false,
  jobs: [],
};

const $ = (selector) => document.querySelector(selector);
const ACTIVE_STATUSES = new Set(["waiting", "downloading", "analyzing", "clipping"]);

const elements = {
  urlCount: $('#urlCount'),
  form: $("#clipForm"),
  urls: $("#youtubeUrls"),
  urlField: $("#urlField"),
  urlError: $("#urlError"),
  speed: $("#speedSelect"),
  quality: $("#qualitySelect"),
  startButton: $("#startButton"),
  startButtonLabel: $("#startButtonLabel"),
  healthPill: $("#healthPill"),
  healthLabel: $("#healthLabel"),
  workspace: $("#workspace"),
  queueCount: $("#queueCount"),
  queueList: $("#queueList"),
  queueNotice: $("#queueNotice"),
  systemNotice: $("#systemNotice"),
  systemMessage: $("#systemMessage"),
  performanceNotice: $("#performanceNotice"),
  performanceMessage: $("#performanceMessage"),
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

function setSubmitting(submitting) {
  state.submitting = submitting;
  elements.startButton.disabled = submitting || !state.ready;
  elements.startButtonLabel.textContent = submitting
    ? "Adding…"
    : state.ready
      ? "Add to queue"
      : "Setup needed";
}

async function checkHealth() {
  elements.healthPill.className = "health-pill is-checking";
  elements.healthLabel.textContent = "Checking";
  try {
    const health = await request("/api/health");
    state.ready = true;
    elements.healthPill.className = "health-pill is-ready";
    elements.healthLabel.textContent = "Ready";
    elements.healthPill.title = `Ollama models: ${health.models.join(", ")}`;
    elements.systemNotice.classList.add("is-hidden");
    const warnings = health.warnings || [];
    elements.performanceMessage.textContent = warnings.join(" ");
    elements.performanceNotice.classList.toggle("is-hidden", warnings.length === 0);
    $("#versionBadge").textContent = `v${health.version}`;
    $("#footerVersion").textContent = `v${health.version}`;
  } catch (error) {
    state.ready = false;
    elements.healthPill.className = "health-pill is-error";
    elements.healthLabel.textContent = "Setup needed";
    elements.healthPill.title = error.message;
    elements.systemMessage.textContent = error.message;
    elements.systemNotice.classList.remove("is-hidden");
    elements.performanceNotice.classList.add("is-hidden");
  }
  setSubmitting(false);
}

function setUrlError(message = "") {
  elements.urlError.textContent = message;
  elements.urlField.classList.toggle("has-error", Boolean(message));
}

function youtubeVideoId(value) {
  try {
    const parsed = new URL(value);
    const host = parsed.hostname.toLowerCase();
    if (parsed.protocol !== "http:" && parsed.protocol !== "https:") return null;
    if (host === "youtu.be") return parsed.pathname.split("/").filter(Boolean)[0] || null;
    if (host !== "youtube.com" && !host.endsWith(".youtube.com")) return null;
    if (parsed.pathname.replace(/\/$/, "") === "/watch") return parsed.searchParams.get("v");
    const parts = parsed.pathname.split("/").filter(Boolean);
    if (["shorts", "embed", "live"].includes(parts[0])) return parts[1] || null;
  } catch {
    return null;
  }
  return null;
}

function updateUrlCount() {
  const value = elements.urls.value;
  const parsed = parseUrls(value);
  const count = parsed.urls.length;
  elements.urlCount.textContent = `${count} URL${count === 1 ? '' : 's'}`;
}

function parseUrls(value) {
  const urls = [];
  const seen = new Set();
  let duplicates = 0;
  const invalid = [];
  for (const candidate of value.split(/\s+/).map((item) => item.trim()).filter(Boolean)) {
    const videoId = youtubeVideoId(candidate);
    if (!videoId || !/^[A-Za-z0-9_-]+$/.test(videoId)) {
      invalid.push(candidate);
    } else if (seen.has(videoId)) {
      duplicates += 1;
    } else {
      seen.add(videoId);
      urls.push(candidate);
    }
  }
  return { urls, duplicates, invalid };
}

async function addToQueue(event) {
  event.preventDefault();
  const parsed = parseUrls(elements.urls.value);
  if (parsed.invalid.length) {
    setUrlError(`${parsed.invalid.length} link${parsed.invalid.length === 1 ? " is" : "s are"} not a valid YouTube video URL`);
    elements.urls.focus();
    return;
  }
  if (!parsed.urls.length) {
    setUrlError("Add at least one YouTube video link");
    elements.urls.focus();
    return;
  }
  setUrlError();
  setSubmitting(true);
  try {
    const submission = await request("/api/jobs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        urls: parsed.urls,
        speed: Number(elements.speed.value),
        whisper_model: elements.quality.value,
      }),
    });
    elements.urls.value = "";
    const duplicateCount = parsed.duplicates + (submission.duplicates || []).length;
    showQueueNotice(
      duplicateCount
        ? `${duplicateCount} duplicate link${duplicateCount === 1 ? " was" : "s were"} skipped.`
        : "",
    );
    await loadQueue();
    elements.workspace.scrollIntoView({ behavior: "smooth", block: "start" });
  } catch (error) {
    setUrlError(error.message);
  } finally {
    setSubmitting(false);
  }
}

function showQueueNotice(message) {
  elements.queueNotice.textContent = message;
  elements.queueNotice.classList.toggle("is-hidden", !message);
}

function schedulePoll() {
  window.clearTimeout(state.pollTimer);
  if (state.jobs.some((job) => ACTIVE_STATUSES.has(job.status))) {
    state.pollTimer = window.setTimeout(loadQueue, 1000);
  }
}

async function loadQueue() {
  try {
    const payload = await request("/api/jobs");
    state.jobs = payload.jobs || [];
    renderQueue();
    schedulePoll();
  } catch (error) {
    showQueueNotice(error.message);
  }
}

function renderQueue() {
  elements.workspace.classList.toggle("is-hidden", state.jobs.length === 0);
  elements.queueCount.textContent = `${state.jobs.length} video${state.jobs.length === 1 ? "" : "s"}`;
  elements.queueList.replaceChildren();
  state.jobs.forEach((job, index) => elements.queueList.append(createJobCard(job, index)));
}

function elapsedTime(createdAt) {
  const elapsedSeconds = Math.max(0, Math.floor((Date.now() - Date.parse(createdAt)) / 1000));
  const minutes = Math.floor(elapsedSeconds / 60);
  const seconds = String(elapsedSeconds % 60).padStart(2, "0");
  return `${minutes}:${seconds}`;
}

function createJobCard(job, index) {
  const card = document.createElement("article");
  card.className = `queue-item status-${job.status}`;

  const header = document.createElement("div");
  header.className = "queue-item-header";
  const identity = document.createElement("div");
  identity.className = "queue-identity";
  const label = document.createElement("span");
  label.textContent = `Video ${index + 1}`;
  const title = document.createElement("h3");
  title.textContent = job.video_id || "YouTube video";
  const url = document.createElement("a");
  url.href = job.url;
  url.target = "_blank";
  url.rel = "noreferrer";
  url.textContent = job.url;
  identity.append(label, title, url);

  const actions = document.createElement("div");
  actions.className = "queue-actions";
  const status = document.createElement("span");
  status.className = `status-badge status-${job.status}`;
  status.textContent = job.status;
  actions.append(status);
  if (job.status === "waiting") {
    const remove = document.createElement("button");
    remove.type = "button";
    remove.className = "remove-button";
    remove.dataset.jobId = job.id;
    remove.textContent = "Remove";
    actions.append(remove);
  }
  header.append(identity, actions);
  card.append(header);

  if (ACTIVE_STATUSES.has(job.status) && job.status !== "waiting") {
    const progress = Math.max(0, Math.min(100, Number(job.progress) || 0));
    const progressRow = document.createElement("div");
    progressRow.className = "job-progress-row";
    const stage = document.createElement("span");
    stage.textContent = `${job.stage} · Elapsed ${elapsedTime(job.created_at)}`;
    const percent = document.createElement("strong");
    percent.textContent = `${progress}%`;
    progressRow.append(stage, percent);
    const track = document.createElement("div");
    track.className = "job-progress-track";
    const fill = document.createElement("span");
    fill.style.width = `${progress}%`;
    track.append(fill);
    card.append(progressRow, track);
  } else if (job.status === "waiting") {
    const waiting = document.createElement("p");
    waiting.className = "job-message";
    waiting.textContent = "Waiting for earlier videos to finish.";
    card.append(waiting);
  }

  if (job.status === "failed") {
    const error = document.createElement("p");
    error.className = "job-error";
    error.textContent = job.error || "This video could not be processed.";
    card.append(error);
  }
  if (job.status === "completed") {
    const clips = document.createElement("div");
    clips.className = "clip-grid";
    (job.clips || []).forEach((clip) => clips.append(createClipCard(clip)));
    card.append(clips);
  }
  if ((job.events || []).length) card.append(createEventLog(job.events));
  return card;
}

function createClipCard(clip) {
  const card = document.createElement("article");
  card.className = "clip-card";
  const title = document.createElement("div");
  title.className = "clip-title";
  title.textContent = clip.name;
  const preview = document.createElement("div");
  preview.className = "clip-preview";
  const video = document.createElement("video");
  video.src = clip.url;
  video.controls = true;
  video.preload = "metadata";
  video.playsInline = true;
  preview.append(video);
  const download = document.createElement("a");
  download.className = "download-button";
  download.href = clip.url;
  download.download = clip.name;
  download.textContent = "Download";
  card.append(title, preview, download);
  return card;
}

function createEventLog(events) {
  const details = document.createElement("details");
  details.className = "activity-log";
  const summary = document.createElement("summary");
  summary.textContent = "Activity";
  const list = document.createElement("ol");
  events.forEach((event) => {
    const item = document.createElement("li");
    const time = new Date(event.time).toLocaleTimeString([], {
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
    });
    item.textContent = `${time} — ${event.stage} (${event.progress}%)`;
    list.append(item);
  });
  details.append(summary, list);
  return details;
}

async function removeWaiting(jobId) {
  try {
    await request(`/api/jobs/${jobId}`, { method: "DELETE" });
    await loadQueue();
  } catch (error) {
    showQueueNotice(error.message);
    await loadQueue();
  }
}

$("#pasteButton").addEventListener("click", async () => {
  try {
    const pasted = await navigator.clipboard.readText();
    elements.urls.value = [elements.urls.value.trim(), pasted.trim()].filter(Boolean).join("\n");
    setUrlError();
  } catch {
    // Clipboard access can be denied; focusing still makes manual paste immediate.
  updateUrlCount();
  }
  elements.urls.focus();
});

elements.urls.addEventListener("input", () => {
  setUrlError();
  updateUrlCount();
});
elements.form.addEventListener("submit", addToQueue);
elements.healthPill.addEventListener("click", checkHealth);
elements.queueList.addEventListener("click", (event) => {
  const button = event.target.closest("button[data-job-id]");
  if (button) removeWaiting(button.dataset.jobId);
});

checkHealth();
loadQueue();
