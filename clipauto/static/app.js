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

let batchId = null;
let pollTimer = null;
const outputSpeed = 1.10;

const terminal = new Set(['completed', 'failed', 'cancelled']);
const stageNames = {
  waiting: 'Waiting', downloading: 'Downloading', transcribing: 'Transcribing',
  segmenting: 'Detecting topics', rendering: 'Creating clips', completed: 'Complete',
  failed: 'Failed', cancelled: 'Cancelled'
};

function parsedCount() {
  const parts = urls.value.split(/[\s,]+/).filter(Boolean);
  return new Set(parts).size;
}

urls.addEventListener('input', () => {
  const total = parsedCount();
  count.textContent = `${total} / 200`;
  count.style.color = total > 200 ? '#b43d2f' : '';
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

form.addEventListener('submit', async (event) => {
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
    const batch = await api('/api/batches', {
      method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({urls: urls.value})
    });
    batchId = batch.id;
    urls.value = '';
    urls.dispatchEvent(new Event('input'));
    queueElement.replaceChildren();
    exportStatus.hidden = true;
    renderBatch(batch);
    workspace.scrollIntoView({behavior: 'smooth', block: 'start'});
    schedulePoll();
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

function renderClips(container, job) {
  const signature = job.clips.map(clip => `${clip.id}:${clip.title}:${clip.start}:${clip.end}`).join(',');
  if (container.dataset.signature === signature) return;
  container.dataset.signature = signature;
  container.replaceChildren();
  job.clips.forEach((clip, index) => {
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
    deleteButton.textContent = 'Delete clip';
    deleteButton.addEventListener('click', async () => {
      if (!window.confirm(`Delete clip “${clip.title}”?`)) return;
      deleteButton.disabled = true;
      deleteButton.textContent = 'Deleting…';
      try {
        await api(`/api/clips/${encodeURIComponent(clip.id)}`, {method: 'DELETE'});
        showJobNotice(container.closest('.job'), 'Clip deleted.');
        await refresh();
      } catch (error) {
        deleteButton.disabled = false;
        deleteButton.textContent = 'Delete clip';
        showJobNotice(container.closest('.job'), error.message, true);
      }
    });
    actions.append(link, deleteButton);
    copy.append(meta, title, actions);
    card.append(video, copy);
    container.append(card);
  });
}

function getJobElement(job) {
  let element = queueElement.querySelector(`[data-job-id="${job.id}"]`);
  if (!element) {
    element = template.content.firstElementChild.cloneNode(true);
    element.dataset.jobId = job.id;
    const clips = element.querySelector('.clips');
    const clipsToggle = element.querySelector('.clips-toggle');
    clips.id = `clips-${job.id}`;
    clipsToggle.setAttribute('aria-controls', clips.id);
    clipsToggle.addEventListener('click', () => {
      const expanded = clipsToggle.getAttribute('aria-expanded') === 'true';
      clipsToggle.setAttribute('aria-expanded', String(!expanded));
      if (expanded) {
        clips.replaceChildren();
        delete clips.dataset.signature;
      } else if (element.latestJob) {
        renderClips(clips, element.latestJob);
      }
      updateClipsToggle(element);
    });
    element.querySelector('.cancel-button').addEventListener('click', async (event) => {
      event.currentTarget.disabled = true;
      try { await api(`/api/jobs/${job.id}/cancel`, {method: 'POST'}); }
      catch (error) {
        event.currentTarget.disabled = false;
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
    element.querySelector('.retry-button').addEventListener('click', async (event) => {
      const button = event.currentTarget;
      button.disabled = true;
      button.textContent = 'Queuing…';
      try {
        await api(`/api/jobs/${job.id}/retry`, {method: 'POST'});
        showJobNotice(element, 'Queued for another attempt.');
        await refresh();
      } catch (error) {
        button.disabled = false;
        button.textContent = 'Retry';
        showJobNotice(element, error.message, true);
      }
    });
    element.querySelector('.remove-button').addEventListener('click', async (event) => {
      const button = event.currentTarget;
      const name = element.querySelector('.job-title').textContent;
      if (!window.confirm(`Delete “${name}” and all of its clips?`)) return;
      button.disabled = true;
      button.textContent = 'Deleting…';
      try {
        const result = await api(`/api/jobs/${job.id}`, {method: 'DELETE'});
        element.remove();
        if (result.batch_deleted) {
          clearTimeout(pollTimer);
          batchId = null;
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
    queueElement.append(element);
  }
  return element;
}

function updateClipsToggle(element) {
  const button = element.querySelector('.clips-toggle');
  const clipCount = element.latestJob?.clips.length || 0;
  const expanded = button.getAttribute('aria-expanded') === 'true';
  button.hidden = clipCount === 0;
  button.textContent = `${expanded ? 'Hide' : 'Show'} ${clipCount} ${clipCount === 1 ? 'clip' : 'clips'}`;
}

function renderJob(job) {
  const element = getJobElement(job);
  element.latestJob = job;
  if (element.dataset.updatedAt === job.updated_at) return;
  element.dataset.updatedAt = job.updated_at;
  const percent = Math.round(job.progress * 100);
  const stage = job.stage === 'rendering' && job.planned_clips
    ? `Creating ${job.planned_clips} ${job.planned_clips === 1 ? 'clip' : 'clips'}`
    : (stageNames[job.stage] || job.stage);
  element.dataset.status = job.status;
  element.querySelector('.job-index').textContent = `Video ${String(job.position + 1).padStart(2, '0')}`;
  element.querySelector('.job-title').textContent = job.title || 'Reading video details…';
  element.querySelector('.job-url').textContent = job.url;
  element.querySelector('.stage-label').textContent = stage;
  element.querySelector('.progress-value').textContent = `${percent}%`;
  const track = element.querySelector('.progress-track');
  track.setAttribute('aria-valuenow', String(percent));
  track.setAttribute('aria-label', `${stage}: ${percent}%`);
  track.querySelector('span').style.width = `${percent}%`;
  element.querySelector('.cancel-button').hidden = terminal.has(job.status);
  element.querySelector('.remove-button').hidden = job.status === 'running';
  const retry = element.querySelector('.retry-button');
  retry.hidden = !['failed', 'cancelled'].includes(job.status);
  if (retry.hidden) retry.disabled = false;
  if (!retry.disabled) retry.textContent = 'Retry';
  const failure = element.querySelector('.job-error');
  failure.textContent = job.error || '';
  failure.hidden = !job.error;
  updateClipsToggle(element);
  if (element.querySelector('.clips-toggle').getAttribute('aria-expanded') === 'true') {
    renderClips(element.querySelector('.clips'), job);
  }
}

function renderBatch(batch) {
  workspace.hidden = false;
  queueElement.setAttribute('aria-busy', String(batch.jobs.some(job => !terminal.has(job.status))));
  batch.jobs.forEach(renderJob);
  const currentIds = new Set(batch.jobs.map(job => job.id));
  queueElement.querySelectorAll('[data-job-id]').forEach(element => {
    if (!currentIds.has(element.dataset.jobId)) element.remove();
  });
  const completed = batch.jobs.filter(job => job.status === 'completed');
  const failed = batch.jobs.filter(job => job.status === 'failed').length;
  const active = batch.jobs.filter(job => !terminal.has(job.status)).length;
  const clipCount = completed.reduce((total, job) => total + job.clips.length, 0);
  summary.textContent = `${completed.length}/${batch.jobs.length} videos complete · ${clipCount} clips · ${active} active${failed ? ` · ${failed} failed` : ''}`;
  downloadAll.href = `/api/batches/${batch.id}/download`;
  downloadAll.hidden = clipCount === 0;
  exportAll.hidden = clipCount === 0;
}

async function refresh() {
  if (!batchId) return;
  try {
    const batch = await api(`/api/batches/${batchId}`);
    renderBatch(batch);
    if (batch.jobs.some(job => !terminal.has(job.status))) schedulePoll();
  } catch (error) {
    summary.textContent = `Status update failed · ${error.message}`;
    schedulePoll(4000);
  }
}

function schedulePoll(delay = 2000) {
  clearTimeout(pollTimer);
  pollTimer = setTimeout(refresh, delay);
}

async function restoreLatestBatch() {
  try {
    const batches = await api('/api/batches');
    if (batches.length) {
      batchId = batches[0].id;
      renderBatch(batches[0]);
      if (batches[0].jobs.some(job => !terminal.has(job.status))) schedulePoll();
    }
  } catch (_) { /* first-run empty state remains useful */ }
}

clearHistory.addEventListener('click', async () => {
  const confirmed = window.confirm(
    'Delete completed, failed, cancelled, and waiting videos? The active video will be kept.'
  );
  if (!confirmed) return;

  clearHistory.disabled = true;
  clearHistory.textContent = 'Clearing…';
  try {
    await api('/api/history', {method: 'DELETE'});
    clearTimeout(pollTimer);
    const batches = await api('/api/batches');
    queueElement.replaceChildren();
    if (!batches.length) {
      batchId = null;
      workspace.hidden = true;
      exportStatus.hidden = true;
      return;
    }
    batchId = batches[0].id;
    renderBatch(batches[0]);
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
