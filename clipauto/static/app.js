const form = document.querySelector('#batch-form');
const urls = document.querySelector('#urls');
const submit = document.querySelector('#create-batch');
const count = document.querySelector('#url-count');
const errorBox = document.querySelector('#form-error');
const workspace = document.querySelector('#workspace');
const queueElement = document.querySelector('#queue');
const summary = document.querySelector('#batch-summary');
const downloadAll = document.querySelector('#download-all');
const clearHistory = document.querySelector('#clear-history');
const exportAll = document.querySelector('#export-all');
const exportStatus = document.querySelector('#export-status');
const template = document.querySelector('#job-template');
const search = document.querySelector('#queue-search');
const visibleCount = document.querySelector('#visible-count');
const loadMore = document.querySelector('#load-more');
const connectionStatus = document.querySelector('#connection-status');
const filterButtons = [...document.querySelectorAll('.filter-button')];

let batchId = null;
let currentBatch = null;
let currentFilter = 'all';
let displayLimit = 30;
let pollTimer = null;
let pollFailures = 0;
let refreshInFlight = false;
const outputSpeed = 1.10;
const clipCache = new Map();

const terminal = new Set(['completed', 'failed', 'cancelled']);
const stageNames = {
  waiting: 'Waiting',
  downloading: 'Downloading source',
  transcribing: 'Transcribing speech',
  segmenting: 'Detecting topics',
  rendering: 'Rendering reels',
  completed: 'Finished',
  failed: 'Needs attention',
  cancelled: 'Cancelled'
};

function parsedCount() {
  return new Set(urls.value.split(/[\s,]+/).filter(Boolean)).size;
}

urls.addEventListener('input', () => {
  const total = parsedCount();
  count.textContent = `${total} / 200`;
  count.dataset.overLimit = String(total > 200);
});

function messageFrom(response) {
  const detail = response?.detail;
  if (typeof detail === 'string') return detail;
  if (detail?.message) {
    return detail.invalid?.length ? `${detail.message}: ${detail.invalid.join(', ')}` : detail.message;
  }
  return 'The request could not be completed.';
}

async function api(path, options) {
  const response = await fetch(path, options);
  if (!response.ok) {
    let body = {};
    try { body = await response.json(); } catch (_) { /* response was not JSON */ }
    throw new Error(messageFrom(body));
  }
  return response.json();
}

function setConnection(state, label) {
  connectionStatus.dataset.state = state;
  connectionStatus.querySelector('b').textContent = label;
}

function normalizeBatch(batch) {
  batch.jobs = batch.jobs.map(job => ({
    ...job,
    clip_count: job.clip_count ?? job.clips?.length ?? 0
  }));
  return batch;
}

form.addEventListener('submit', async event => {
  event.preventDefault();
  errorBox.hidden = true;
  if (!urls.value.trim()) {
    errorBox.textContent = 'Paste at least one YouTube URL.';
    errorBox.hidden = false;
    urls.focus();
    return;
  }
  submit.disabled = true;
  submit.querySelector('span').textContent = 'Adding…';
  try {
    const batch = normalizeBatch(await api('/api/batches', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({urls: urls.value})
    }));
    batchId = batch.id;
    currentFilter = 'active';
    displayLimit = 30;
    urls.value = '';
    urls.dispatchEvent(new Event('input'));
    clipCache.clear();
    exportStatus.hidden = true;
    renderBatch(batch);
    workspace.scrollIntoView({behavior: 'smooth', block: 'start'});
    schedulePoll(500);
  } catch (error) {
    errorBox.textContent = error.message;
    errorBox.hidden = false;
  } finally {
    submit.disabled = false;
    submit.querySelector('span').textContent = 'Create clips';
  }
});

function formatDuration(seconds) {
  const rounded = Math.max(0, Math.round(seconds));
  const minutes = Math.floor(rounded / 60);
  return `${minutes}:${String(rounded % 60).padStart(2, '0')}`;
}

function showJobNotice(element, message, isError = false) {
  const notice = element.querySelector('.job-notice');
  notice.textContent = message;
  notice.classList.toggle('is-error', isError);
  notice.hidden = false;
}

async function copyText(text) {
  if (navigator.clipboard?.writeText) {
    await navigator.clipboard.writeText(text);
    return;
  }
  const input = document.createElement('textarea');
  input.value = text;
  input.setAttribute('readonly', '');
  input.className = 'clipboard-fallback';
  document.body.append(input);
  input.select();
  const copied = document.execCommand('copy');
  input.remove();
  if (!copied) throw new Error('Could not copy the link.');
}

function conciseError(message) {
  const text = message || '';
  if (/resolve|network|connection|timed out/i.test(text)) {
    return 'YouTube could not be reached. Check the connection, then retry.';
  }
  if (/cookie|sign in|403|age|not a bot/i.test(text)) {
    return 'YouTube needs browser access. Sign in with Brave, close it, then retry.';
  }
  if (/space|disk full/i.test(text)) {
    return 'Storage is full. Free some space, then retry.';
  }
  if (/topic|ollama|json|boundar/i.test(text)) {
    return 'Topic detection returned an old unusable result. Retry to use automatic recovery.';
  }
  const firstLine = text.split('\n', 1)[0].replace(/^[^:]+ failed:\s*/i, '').trim();
  return firstLine.length > 150 ? `${firstLine.slice(0, 147)}…` : firstLine;
}

function renderClips(container, element, job, clips) {
  const signature = clips.map(clip => `${clip.id}:${clip.title}:${clip.start}:${clip.end}`).join(',');
  if (container.dataset.signature === signature) return;
  container.dataset.signature = signature;
  container.replaceChildren();
  clips.forEach((clip, index) => {
    const card = document.createElement('article');
    card.className = 'clip-card';
    const video = document.createElement('video');
    video.controls = true;
    video.preload = 'none';
    video.src = `/api/clips/${encodeURIComponent(clip.id)}/media`;
    video.setAttribute('aria-label', `Preview ${clip.title}`);
    const copy = document.createElement('div');
    copy.className = 'clip-copy';
    const meta = document.createElement('p');
    meta.textContent = `Clip ${String(index + 1).padStart(2, '0')} · ${formatDuration((clip.end - clip.start) / outputSpeed)} · 1.10×`;
    const title = document.createElement('h4');
    title.textContent = clip.title;
    const link = document.createElement('a');
    link.href = `/api/clips/${encodeURIComponent(clip.id)}/download`;
    link.textContent = 'Download MP4 ↓';
    const actions = document.createElement('div');
    actions.className = 'clip-actions';
    const deleteButton = document.createElement('button');
    deleteButton.className = 'delete-clip';
    deleteButton.type = 'button';
    deleteButton.textContent = 'Delete';
    deleteButton.addEventListener('click', async () => {
      if (!window.confirm(`Delete clip “${clip.title}”?`)) return;
      deleteButton.disabled = true;
      deleteButton.textContent = 'Deleting…';
      try {
        await api(`/api/clips/${encodeURIComponent(clip.id)}`, {method: 'DELETE'});
        clipCache.delete(job.id);
        showJobNotice(element, 'Clip deleted.');
        await refresh();
      } catch (error) {
        deleteButton.disabled = false;
        deleteButton.textContent = 'Delete';
        showJobNotice(element, error.message, true);
      }
    });
    actions.append(link, deleteButton);
    copy.append(meta, title, actions);
    card.append(video, copy);
    container.append(card);
  });
}

async function toggleClips(element) {
  const button = element.querySelector('.clips-toggle');
  const clips = element.querySelector('.clips');
  const expanded = button.getAttribute('aria-expanded') === 'true';
  button.setAttribute('aria-expanded', String(!expanded));
  if (expanded) {
    clips.replaceChildren();
    delete clips.dataset.signature;
    updateClipsToggle(element);
    return;
  }
  const job = element.latestJob;
  clips.innerHTML = '<p class="clips-loading">Loading clip details…</p>';
  updateClipsToggle(element);
  try {
    let records = clipCache.get(job.id);
    if (!records) {
      records = await api(`/api/jobs/${encodeURIComponent(job.id)}/clips`);
      clipCache.set(job.id, records);
    }
    if (button.getAttribute('aria-expanded') === 'true') {
      renderClips(clips, element, job, records);
    }
  } catch (error) {
    button.setAttribute('aria-expanded', 'false');
    clips.replaceChildren();
    showJobNotice(element, error.message, true);
    updateClipsToggle(element);
  }
}

function getJobElement(job) {
  let element = queueElement.querySelector(`[data-job-id="${job.id}"]`);
  if (element) return element;
  element = template.content.firstElementChild.cloneNode(true);
  element.dataset.jobId = job.id;
  const clips = element.querySelector('.clips');
  const clipsToggle = element.querySelector('.clips-toggle');
  clips.id = `clips-${job.id}`;
  clipsToggle.setAttribute('aria-controls', clips.id);
  clipsToggle.addEventListener('click', () => toggleClips(element));
  element.querySelector('.cancel-button').addEventListener('click', async event => {
    const button = event.currentTarget;
    button.disabled = true;
    button.textContent = 'Cancelling…';
    try {
      await api(`/api/jobs/${job.id}/cancel`, {method: 'POST'});
      showJobNotice(element, 'Cancellation requested.');
      schedulePoll(250);
    } catch (error) {
      button.disabled = false;
      button.textContent = 'Cancel';
      showJobNotice(element, error.message, true);
    }
  });
  element.querySelector('.copy-button').addEventListener('click', async () => {
    try {
      await copyText(element.latestJob?.url || job.url);
      showJobNotice(element, 'Video link copied.');
    } catch (error) {
      showJobNotice(element, error.message, true);
    }
  });
  element.querySelector('.retry-button').addEventListener('click', async event => {
    const button = event.currentTarget;
    button.disabled = true;
    button.textContent = 'Queuing…';
    try {
      await api(`/api/jobs/${job.id}/retry`, {method: 'POST'});
      clipCache.delete(job.id);
      showJobNotice(element, 'Queued. Reusable analysis will be kept.');
      await refresh();
    } catch (error) {
      button.disabled = false;
      button.textContent = 'Retry';
      showJobNotice(element, error.message, true);
    }
  });
  element.querySelector('.remove-button').addEventListener('click', async event => {
    const button = event.currentTarget;
    const name = element.querySelector('.job-title').textContent;
    if (!window.confirm(`Delete “${name}” and all of its clips?`)) return;
    button.disabled = true;
    button.textContent = 'Deleting…';
    try {
      const result = await api(`/api/jobs/${job.id}`, {method: 'DELETE'});
      clipCache.delete(job.id);
      if (result.batch_deleted) {
        clearTimeout(pollTimer);
        batchId = null;
        currentBatch = null;
        workspace.hidden = true;
      } else {
        await refresh();
      }
    } catch (error) {
      button.disabled = false;
      button.textContent = 'Delete video';
      showJobNotice(element, error.message, true);
    }
  });
  return element;
}

function updateClipsToggle(element) {
  const button = element.querySelector('.clips-toggle');
  const clipCount = element.latestJob?.clip_count || 0;
  const expanded = button.getAttribute('aria-expanded') === 'true';
  button.hidden = clipCount === 0;
  button.textContent = `${expanded ? 'Hide' : 'Show'} ${clipCount} ${clipCount === 1 ? 'clip' : 'clips'}`;
}

function renderJob(job) {
  const element = getJobElement(job);
  element.latestJob = job;
  const percent = Math.round(job.progress * 100);
  const stage = job.stage === 'rendering' && job.planned_clips
    ? `Rendering ${job.planned_clips} ${job.planned_clips === 1 ? 'clip' : 'clips'}`
    : (stageNames[job.stage] || job.stage);
  element.dataset.status = job.status;
  element.querySelector('.job-index').textContent = `Video ${String(job.position + 1).padStart(3, '0')}`;
  element.querySelector('.job-title').textContent = job.title || 'Waiting for video details';
  element.querySelector('.job-url').textContent = job.url;
  element.querySelector('.stage-label').textContent = stage;
  element.querySelector('.progress-value').textContent = `${percent}%`;
  const track = element.querySelector('.progress-track');
  track.setAttribute('aria-valuenow', String(percent));
  track.setAttribute('aria-label', `${stage}: ${percent}%`);
  track.querySelector('span').style.width = `${percent}%`;
  const cancel = element.querySelector('.cancel-button');
  cancel.hidden = terminal.has(job.status);
  if (!cancel.hidden && !job.cancel_requested) {
    cancel.disabled = false;
    cancel.textContent = 'Cancel';
  }
  element.querySelector('.remove-button').hidden = job.status === 'running';
  const retry = element.querySelector('.retry-button');
  retry.hidden = !['failed', 'cancelled'].includes(job.status);
  if (!retry.hidden) {
    retry.disabled = false;
    retry.textContent = 'Retry';
  }
  const details = element.querySelector('.error-details');
  details.hidden = !job.error;
  element.querySelector('.error-summary').textContent = job.error ? conciseError(job.error) : '';
  element.querySelector('.job-error').textContent = job.error || '';
  updateClipsToggle(element);
  return element;
}

function countsFor(batch) {
  return {
    all: batch.jobs.length,
    active: batch.jobs.filter(job => !terminal.has(job.status)).length,
    completed: batch.jobs.filter(job => job.status === 'completed').length,
    failed: batch.jobs.filter(job => ['failed', 'cancelled'].includes(job.status)).length
  };
}

function jobMatches(job) {
  const filterMatch = currentFilter === 'all'
    || (currentFilter === 'active' && !terminal.has(job.status))
    || (currentFilter === 'completed' && job.status === 'completed')
    || (currentFilter === 'failed' && ['failed', 'cancelled'].includes(job.status));
  if (!filterMatch) return false;
  const needle = search.value.trim().toLocaleLowerCase();
  if (!needle) return true;
  return `${job.position + 1} ${job.title || ''} ${job.url}`.toLocaleLowerCase().includes(needle);
}

function renderQueue() {
  if (!currentBatch) return;
  const matching = currentBatch.jobs.filter(jobMatches);
  const visible = matching.slice(0, displayLimit);
  const fragment = document.createDocumentFragment();
  visible.forEach(job => fragment.append(renderJob(job)));
  queueElement.replaceChildren(fragment);
  visibleCount.textContent = matching.length
    ? `Showing ${visible.length} of ${matching.length}`
    : 'No matching videos';
  loadMore.hidden = visible.length >= matching.length;
  loadMore.textContent = `Show ${Math.min(30, matching.length - visible.length)} more`;
}

function renderBatch(batch, {preferActive = false} = {}) {
  currentBatch = normalizeBatch(batch);
  workspace.hidden = false;
  const counts = countsFor(currentBatch);
  if (preferActive && counts.active) currentFilter = 'active';
  queueElement.setAttribute('aria-busy', String(counts.active > 0));
  document.querySelector('#count-all').textContent = counts.all;
  document.querySelector('#count-active').textContent = counts.active;
  document.querySelector('#count-completed').textContent = counts.completed;
  document.querySelector('#count-failed').textContent = counts.failed;
  filterButtons.forEach(button => {
    button.setAttribute('aria-pressed', String(button.dataset.filter === currentFilter));
  });
  const clipCount = currentBatch.jobs.reduce((total, job) => total + job.clip_count, 0);
  summary.textContent = `${clipCount.toLocaleString()} clips across ${counts.all} videos`;
  downloadAll.href = `/api/batches/${batch.id}/download`;
  downloadAll.hidden = clipCount === 0;
  exportAll.hidden = clipCount === 0;
  renderQueue();
}

async function refresh() {
  if (!batchId || refreshInFlight) return;
  refreshInFlight = true;
  setConnection('connecting', pollFailures ? 'Retrying' : 'Refreshing');
  try {
    const batch = await api(`/api/batches/${batchId}?include_clips=false`);
    pollFailures = 0;
    renderBatch(batch);
    setConnection('live', 'Live');
    if (batch.jobs.some(job => !terminal.has(job.status))) schedulePoll();
  } catch (error) {
    pollFailures += 1;
    setConnection('offline', navigator.onLine ? 'Reconnecting' : 'Offline');
    summary.textContent = `Updates paused · ${error.message}`;
    schedulePoll(Math.min(15000, 2000 * 2 ** pollFailures));
  } finally {
    refreshInFlight = false;
  }
}

function schedulePoll(delay = 2000) {
  clearTimeout(pollTimer);
  if (document.hidden) return;
  pollTimer = setTimeout(refresh, delay);
}

async function restoreLatestBatch() {
  setConnection('connecting', 'Connecting');
  try {
    const batches = await api('/api/batches?include_clips=false');
    setConnection('live', 'Live');
    if (batches.length) {
      batchId = batches[0].id;
      renderBatch(batches[0], {preferActive: true});
      if (batches[0].jobs.some(job => !terminal.has(job.status))) schedulePoll();
    }
  } catch (_) {
    setConnection('offline', navigator.onLine ? 'Unavailable' : 'Offline');
  }
}

filterButtons.forEach(button => button.addEventListener('click', () => {
  currentFilter = button.dataset.filter;
  displayLimit = 30;
  filterButtons.forEach(item => {
    item.setAttribute('aria-pressed', String(item === button));
  });
  renderQueue();
}));

search.addEventListener('input', () => {
  displayLimit = 30;
  renderQueue();
});

loadMore.addEventListener('click', () => {
  displayLimit += 30;
  renderQueue();
});

document.addEventListener('visibilitychange', () => {
  if (document.hidden) clearTimeout(pollTimer);
  else if (batchId) refresh();
});

window.addEventListener('offline', () => setConnection('offline', 'Offline'));
window.addEventListener('online', () => {
  setConnection('connecting', 'Reconnecting');
  if (batchId) refresh();
});

clearHistory.addEventListener('click', async () => {
  if (!window.confirm('Delete finished, failed, cancelled, and waiting videos? Active work stays.')) return;
  clearHistory.disabled = true;
  clearHistory.textContent = 'Clearing…';
  try {
    await api('/api/history', {method: 'DELETE'});
    clearTimeout(pollTimer);
    clipCache.clear();
    const batches = await api('/api/batches?include_clips=false');
    if (!batches.length) {
      batchId = null;
      currentBatch = null;
      queueElement.replaceChildren();
      workspace.hidden = true;
      exportStatus.hidden = true;
      return;
    }
    batchId = batches[0].id;
    renderBatch(batches[0], {preferActive: true});
    if (batches[0].jobs.some(job => !terminal.has(job.status))) schedulePoll();
  } catch (error) {
    window.alert(error.message);
  } finally {
    clearHistory.disabled = false;
    clearHistory.textContent = 'Clear history';
  }
});

exportAll.addEventListener('click', async () => {
  if (!batchId) return;
  exportAll.disabled = true;
  exportAll.firstChild.textContent = 'Exporting… ';
  exportStatus.textContent = 'Copying completed clips to Downloads…';
  exportStatus.hidden = false;
  try {
    const result = await api(`/api/batches/${batchId}/export`, {method: 'POST'});
    const folderName = result.folder.split(/[\\/]/).filter(Boolean).pop();
    exportStatus.textContent = `Saved ${result.files} MP4${result.files === 1 ? '' : 's'} to Downloads/${folderName}`;
    exportStatus.title = result.folder;
  } catch (error) {
    exportStatus.textContent = error.message;
    exportStatus.removeAttribute('title');
  } finally {
    exportAll.disabled = false;
    exportAll.firstChild.textContent = 'Export MP4s ';
  }
});

restoreLatestBatch();
