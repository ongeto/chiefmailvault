/* ChiefMailVault Dashboard */

const API = '';
let selectedDomainId = localStorage.getItem('cmv_selected_domain') || '';
let selectedTriageMailboxId = localStorage.getItem('cmv_triage_mailbox') || '';
let allDomains = [];
let allMailboxes = [];
let mailboxValidated = false;
let editValidated = true;

function domainQuery() {
  return selectedDomainId ? `?domain_id=${selectedDomainId}` : '';
}

function triageQuery() {
  const params = new URLSearchParams();
  if (selectedTriageMailboxId) {
    params.set('mailbox_id', selectedTriageMailboxId);
  } else if (selectedDomainId) {
    params.set('domain_id', selectedDomainId);
  }
  const q = params.toString();
  return q ? `?${q}` : '';
}

function scopeBody() {
  const body = {};
  if (selectedTriageMailboxId) body.mailbox_id = +selectedTriageMailboxId;
  else if (selectedDomainId) body.domain_id = +selectedDomainId;
  return body;
}

function mailboxesForScope() {
  return selectedDomainId
    ? allMailboxes.filter(m => String(m.domain_id) === String(selectedDomainId))
    : allMailboxes;
}

async function api(path, options = {}) {
  const res = await fetch(API + path, {
    credentials: 'include',
    headers: { 'Content-Type': 'application/json', ...options.headers },
    ...options,
  });
  if (res.status === 401 && !path.includes('/auth/')) {
    showLogin();
    throw new Error('Unauthorized');
  }
  const data = res.headers.get('content-type')?.includes('json') ? await res.json() : null;
  if (!res.ok) throw new Error(data?.detail || res.statusText);
  return data;
}

function showLogin() {
  document.getElementById('login-view').classList.remove('hidden');
  document.getElementById('dashboard-view').classList.add('hidden');
}

function showDashboard(username) {
  document.getElementById('login-view').classList.add('hidden');
  document.getElementById('dashboard-view').classList.remove('hidden');
  document.getElementById('user-label').textContent = username;
  loadAll();
  connectLogs();
}

function formatBytes(b) {
  if (!b) return '0 B';
  const u = ['B', 'KB', 'MB', 'GB'];
  const i = Math.floor(Math.log(b) / Math.log(1024));
  return (b / Math.pow(1024, i)).toFixed(1) + ' ' + u[i];
}

const APP_TIMEZONE = 'Africa/Nairobi';

function formatDate(iso) {
  if (!iso) return '—';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return String(iso).slice(0, 10);
  return d.toLocaleDateString('en-KE', {
    timeZone: APP_TIMEZONE,
    year: 'numeric',
    month: 'short',
    day: 'numeric',
  });
}

function formatLogTime(iso) {
  if (!iso) return '';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return String(iso);
  return d.toLocaleString('en-KE', {
    timeZone: APP_TIMEZONE,
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
  });
}

async function loadStats() {
  const s = await api('/api/stats' + domainQuery());
  document.getElementById('stat-domains').textContent = s.domains;
  document.getElementById('stat-mailboxes').textContent = s.mailboxes;
  document.getElementById('stat-messages').textContent = s.messages;
  document.getElementById('stat-duplicates').textContent = s.duplicates;
  document.getElementById('stat-large').textContent = s.large_emails;
}

async function loadDuplicates() {
  const dups = await api('/api/duplicates' + triageQuery());
  const tbody = document.getElementById('duplicates-body');
  const mailboxHint = selectedTriageMailboxId ? ' for this mailbox' : '';
  const emptyHint = selectedDomainId || selectedTriageMailboxId
    ? `No duplicates${mailboxHint}. Run backup on this mailbox after sending to yourself.`
    : 'No inbox/sent duplicates yet. Send an email to yourself, run backup — both copies must land in Inbox and Sent (not Trash).';
  tbody.innerHTML = dups.length ? dups.map(d => `
    <tr class="border-t border-slate-700">
      <td class="p-2"><input type="checkbox" class="dup-cb" value="${d.id}"></td>
      <td class="p-2">${d.mailbox_email || ''}</td>
      <td class="p-2 truncate max-w-xs" title="${d.subject || d.message_id || ''}">${(d.subject || d.message_id || '(no subject)').slice(0, 40)}</td>
      <td class="p-2 text-slate-400 whitespace-nowrap">${formatDate(d.date)}</td>
      <td class="p-2 text-center"><span class="px-2 py-0.5 rounded text-xs ${d.status === 'flagged' || d.status === 'flagged_deleted' ? 'bg-amber-900 text-amber-300' : 'bg-slate-700'}">${d.status}</span></td>
    </tr>
  `).join('') : `<tr><td colspan="5" class="p-4 text-center text-slate-500 text-xs leading-relaxed">${emptyHint}</td></tr>`;
}

function statusBadge(status) {
  if (status === 'flagged_deleted') return 'bg-amber-900 text-amber-300';
  if (status === 'purged') return 'bg-green-900 text-green-300';
  if (status === 'approved') return 'bg-blue-900 text-blue-300';
  return 'bg-slate-700';
}

async function loadLargeEmails() {
  const items = await api('/api/large-emails' + triageQuery());
  const tbody = document.getElementById('large-emails-body');
  tbody.innerHTML = items.length ? items.map(m => `
    <tr class="border-t border-slate-700">
      <td class="p-2"><input type="checkbox" class="large-cb" value="${m.id}" ${m.purge_status === 'flagged_deleted' ? 'disabled' : ''}></td>
      <td class="p-2">${m.mailbox_email || ''}</td>
      <td class="p-2 truncate max-w-xs" title="${m.subject || ''}">${(m.subject || '(no subject)').slice(0, 40)}</td>
      <td class="p-2 text-slate-400 whitespace-nowrap">${formatDate(m.date)}</td>
      <td class="p-2 text-right text-red-300">${formatBytes(m.size)}</td>
      <td class="p-2 text-center"><span class="px-2 py-0.5 rounded text-xs ${statusBadge(m.purge_status || 'pending')}">${m.purge_status || 'pending'}</span></td>
    </tr>
  `).join('') : '<tr><td colspan="6" class="p-4 text-center text-slate-500">No large emails</td></tr>';
}

async function loadSuggestions() {
  const sugs = await api('/api/cleanup/suggestions' + triageQuery());
  const tbody = document.getElementById('suggestions-body');
  tbody.innerHTML = sugs.length ? sugs.map(s => {
    const done = s.status === 'flagged_deleted' || s.executed;
    return `
    <tr class="border-t border-slate-700">
      <td class="p-2">${done ? '' : `<input type="checkbox" class="sug-cb" value="${s.id}">`}</td>
      <td class="p-2 whitespace-nowrap">${s.mailbox_email || ''}</td>
      <td class="p-2 truncate max-w-xs" title="${s.subject || ''}">${(s.subject || '(no subject)').slice(0, 40)}</td>
      <td class="p-2 text-slate-400 whitespace-nowrap">${formatDate(s.date)}</td>
      <td class="p-2 whitespace-nowrap">${s.category_label || s.category}</td>
      <td class="p-2 text-slate-400 truncate max-w-xs" title="${s.reason || ''}">${(s.reason || '').slice(0, 45)}</td>
      <td class="p-2 text-center"><span class="px-2 py-0.5 rounded text-xs ${statusBadge(s.status || 'pending')}">${s.status || 'pending'}</span></td>
    </tr>`;
  }).join('') : '<tr><td colspan="7" class="p-4 text-center text-slate-500">No suggestions — run AI Scan after backup</td></tr>';
}

function populateDomainSelects() {
  const options = allDomains.map(d => `<option value="${d.id}">${d.name}</option>`).join('');
  const navSel = document.getElementById('nav-domain-select');
  const mailboxSel = document.getElementById('mailbox-domain');
  const editSel = document.getElementById('edit-mailbox-domain');

  navSel.innerHTML = '<option value="">All Domains</option>' + options;
  navSel.value = selectedDomainId;
  mailboxSel.innerHTML = options;
  if (selectedDomainId) {
    mailboxSel.value = selectedDomainId;
  }
  editSel.innerHTML = options;
}

function populateTriageMailboxSelect() {
  const sel = document.getElementById('triage-mailbox-select');
  if (!sel) return;
  const mailboxes = mailboxesForScope();
  if (
    selectedTriageMailboxId
    && !mailboxes.some(m => String(m.id) === String(selectedTriageMailboxId))
  ) {
    selectedTriageMailboxId = '';
    localStorage.removeItem('cmv_triage_mailbox');
  }
  sel.innerHTML = '<option value="">All mailboxes</option>'
    + mailboxes.map(m => `<option value="${m.id}">${m.email}</option>`).join('');
  sel.value = selectedTriageMailboxId;
}

async function loadTriage() {
  await Promise.all([loadDuplicates(), loadLargeEmails(), loadSuggestions(), loadRestorable()]);
}

async function loadDomains() {
  allDomains = await api('/api/domains');
  populateDomainSelects();
}

async function loadMailboxes() {
  allMailboxes = await api('/api/mailboxes');
  const mailboxes = mailboxesForScope();
  populateTriageMailboxSelect();
  const list = document.getElementById('mailbox-list');

  list.innerHTML = mailboxes.length ? mailboxes.map(m => {
    const integ = m.integrity || {};
    const total = integ.total || 0;
    const ok = integ.ok || 0;
    const ready = integ.restore_ready;
    const integLabel = total
      ? (ready
        ? `<span class="text-green-400">${ok}/${total} restore-ready</span>`
        : `<span class="text-amber-400">${ok}/${total} verified</span>`)
      : '<span class="text-slate-500">No backups</span>';
    return `
    <div class="flex flex-wrap justify-between items-center py-2 border-b border-slate-700/50 gap-2">
      <div>
        <span class="font-medium">${m.email}</span>
        <span class="text-slate-500 text-xs ml-2">${m.domain_name}</span>
        <span class="text-xs ml-2">${m.credentials_validated ? '<span class="text-green-400">Validated</span>' : '<span class="text-amber-400">Not validated</span>'}</span>
        <span class="text-xs ml-2">${integLabel}</span>
      </div>
      <div class="flex flex-wrap gap-2 shrink-0">
        <button type="button" class="btn-verify-mailbox px-2 py-1 text-xs bg-slate-600 hover:bg-slate-500 rounded" data-id="${m.id}">Verify Backups</button>
        <button type="button" class="btn-flag-verified px-2 py-1 text-xs bg-amber-700 hover:bg-amber-600 rounded" data-id="${m.id}" data-email="${m.email}">Flag Verified</button>
        <button type="button" class="btn-revalidate-mailbox px-2 py-1 text-xs bg-slate-600 hover:bg-slate-500 rounded" data-id="${m.id}">Revalidate</button>
        <button type="button" class="btn-edit-mailbox px-2 py-1 text-xs bg-slate-600 hover:bg-slate-500 rounded" data-id="${m.id}">Edit</button>
        <button type="button" class="btn-delete-mailbox px-2 py-1 text-xs bg-red-700 hover:bg-red-600 rounded" data-id="${m.id}" data-email="${m.email}">Delete</button>
      </div>
    </div>`;
  }).join('') : '<p class="text-slate-500">No mailboxes configured</p>';

  list.querySelectorAll('.btn-verify-mailbox').forEach(btn => {
    btn.addEventListener('click', () => verifyMailboxBackups(+btn.dataset.id, btn));
  });
  list.querySelectorAll('.btn-flag-verified').forEach(btn => {
    btn.addEventListener('click', () => flagVerifiedMailbox(+btn.dataset.id, btn.dataset.email, btn));
  });
  list.querySelectorAll('.btn-revalidate-mailbox').forEach(btn => {
    btn.addEventListener('click', () => revalidateMailbox(+btn.dataset.id, btn));
  });
  list.querySelectorAll('.btn-edit-mailbox').forEach(btn => {
    btn.addEventListener('click', () => openEditModal(+btn.dataset.id));
  });
  list.querySelectorAll('.btn-delete-mailbox').forEach(btn => {
    btn.addEventListener('click', () => deleteMailbox(+btn.dataset.id, btn.dataset.email));
  });

  const expSel = document.getElementById('expunge-mailbox');
  expSel.innerHTML = mailboxes.map(m => `<option value="${m.id}">${m.email}</option>`).join('');
  if (
    selectedTriageMailboxId
    && mailboxes.some(m => String(m.id) === String(selectedTriageMailboxId))
  ) {
    expSel.value = selectedTriageMailboxId;
  }
}

function setValidationMessage(ok, message) {
  const el = document.getElementById('mailbox-validation-msg');
  el.textContent = message;
  el.classList.remove('hidden', 'text-green-400', 'text-red-400');
  el.classList.add(ok ? 'text-green-400' : 'text-red-400');
  mailboxValidated = ok;
  document.getElementById('btn-add-mailbox').disabled = !ok;
}

function resetMailboxValidation() {
  mailboxValidated = false;
  document.getElementById('btn-add-mailbox').disabled = true;
  const el = document.getElementById('mailbox-validation-msg');
  el.classList.add('hidden');
  el.textContent = '';
}

function setEditValidationMessage(ok, message) {
  const el = document.getElementById('edit-validation-msg');
  el.textContent = message;
  el.classList.remove('hidden', 'text-green-400', 'text-red-400');
  el.classList.add(ok ? 'text-green-400' : 'text-red-400');
  editValidated = ok;
}

function openEditModal(mailboxId, options = {}) {
  const mb = allMailboxes.find(m => m.id === mailboxId);
  if (!mb) return;
  document.getElementById('edit-mailbox-id').value = mailboxId;
  document.getElementById('edit-mailbox-domain').value = mb.domain_id;
  document.getElementById('edit-mailbox-email').value = mb.email;
  document.getElementById('edit-mailbox-password').value = '';
  document.getElementById('edit-validation-msg').classList.add('hidden');
  editValidated = true;
  document.getElementById('edit-mailbox-modal').classList.remove('hidden');
  if (options.error) {
    setEditValidationMessage(false, options.error);
    editValidated = false;
  }
  if (options.focusPassword) {
    const pw = document.getElementById('edit-mailbox-password');
    setTimeout(() => pw.focus(), 50);
  }
}

async function revalidateMailbox(mailboxId, btn) {
  const original = btn.textContent;
  btn.disabled = true;
  btn.textContent = 'Checking...';
  try {
    const result = await api(`/api/mailboxes/${mailboxId}/revalidate`, { method: 'POST' });
    await loadMailboxes();
    if (result.valid) {
      alert(result.message || 'Credentials are valid');
    } else {
      openEditModal(mailboxId, {
        error: result.message || 'Validation failed — update the password',
        focusPassword: true,
      });
    }
  } catch (ex) {
    openEditModal(mailboxId, {
      error: ex.message || 'Revalidation failed — update the password',
      focusPassword: true,
    });
  } finally {
    btn.disabled = false;
    btn.textContent = original;
  }
}

async function verifyMailboxBackups(mailboxId, btn) {
  const original = btn.textContent;
  btn.disabled = true;
  btn.textContent = 'Verifying...';
  try {
    const result = await api(`/api/mailboxes/${mailboxId}/verify`, { method: 'POST' });
    await loadMailboxes();
    if (result.restore_ready) {
      alert(`Restore-ready: ${result.ok}/${result.total} messages verified OK.`);
    } else {
      alert(
        `Integrity: ${result.ok}/${result.total} OK` +
        (result.failed ? `, ${result.failed} failed` : '') +
        '. Fix failed backups before server deletion.'
      );
    }
  } catch (ex) {
    alert(ex.message || 'Verification failed');
  } finally {
    btn.disabled = false;
    btn.textContent = original;
  }
}

async function flagVerifiedMailbox(mailboxId, email, btn) {
  const original = btn.textContent;
  btn.disabled = true;
  btn.textContent = 'Checking...';
  try {
    const preview = await api(`/api/mailboxes/${mailboxId}/flag-verified`, { method: 'POST' });
    if (!preview.count) {
      alert((preview.warnings || ['Nothing to flag']).join('\n'));
      return;
    }
    const warn = [
      `Flag ${preview.count} verified message(s) (~${formatBytes(preview.total_bytes)}) on ${email} for server deletion?`,
      'Local backups are kept. Use Empty Deleted Queue to permanently remove them from Hostinger.',
      ...(preview.warnings || []),
    ].join('\n\n');
    if (!confirm(warn)) return;

    btn.textContent = 'Flagging...';
    const result = await api(`/api/mailboxes/${mailboxId}/flag-verified/execute`, { method: 'POST' });
    await loadMailboxes();
    alert(`Flagged ${result.flagged || 0}, failed ${result.failed || 0}. Expunge when ready.`);
  } catch (ex) {
    alert(ex.message || 'Failed to flag verified messages');
  } finally {
    btn.disabled = false;
    btn.textContent = original;
  }
}

function closeEditModal() {
  document.getElementById('edit-mailbox-modal').classList.add('hidden');
}

async function deleteMailbox(id, email) {
  if (!confirm(`Delete mailbox ${email}? Backed-up emails remain on disk.`)) return;
  await api(`/api/mailboxes/${id}`, { method: 'DELETE' });
  await loadAll();
}

async function loadAll() {
  await loadDomains();
  await loadMailboxes();
  await loadStats();
  await loadTriage();
}

function connectLogs() {
  const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
  const ws = new WebSocket(`${proto}//${location.host}/ws/logs`);
  const term = document.getElementById('log-terminal');
  let refreshTimer;
  const scheduleDataRefresh = () => {
    clearTimeout(refreshTimer);
    refreshTimer = setTimeout(() => {
      loadStats();
      loadTriage();
      loadMailboxes();
    }, 400);
  };
  ws.onmessage = (e) => {
    const entry = JSON.parse(e.data);
    const line = document.createElement('div');
    line.textContent = `[${formatLogTime(entry.time)}] ${entry.message}`;
    term.appendChild(line);
    term.scrollTop = term.scrollHeight;
    if (/Sync complete|Duplicate flagged|Duplicate scan|Backup finished|Archive step done|Restore finished|Integrity audit/i.test(entry.message)) {
      scheduleDataRefresh();
    }
    if (/Backup finished/i.test(entry.message)) {
      const backupBtn = document.getElementById('btn-backup-all');
      if (backupBtn) {
        backupBtn.disabled = false;
        backupBtn.textContent = 'Run Backup';
      }
    }
    if (/Restore finished/i.test(entry.message)) {
      setImportButtonsRunning(false);
    }
  };
}

// Event listeners
document.getElementById('nav-domain-select').addEventListener('change', (e) => {
  selectedDomainId = e.target.value;
  localStorage.setItem('cmv_selected_domain', selectedDomainId);
  if (selectedDomainId) {
    document.getElementById('mailbox-domain').value = selectedDomainId;
    resetMailboxValidation();
  }
  populateTriageMailboxSelect();
  loadAll();
});

document.getElementById('triage-mailbox-select').addEventListener('change', (e) => {
  selectedTriageMailboxId = e.target.value;
  if (selectedTriageMailboxId) {
    localStorage.setItem('cmv_triage_mailbox', selectedTriageMailboxId);
    const expSel = document.getElementById('expunge-mailbox');
    if (expSel) expSel.value = selectedTriageMailboxId;
  } else {
    localStorage.removeItem('cmv_triage_mailbox');
  }
  restoreOffset = 0;
  loadTriage();
});

document.getElementById('login-form').addEventListener('submit', async (e) => {
  e.preventDefault();
  const err = document.getElementById('login-error');
  try {
    const data = await api('/auth/login', {
      method: 'POST',
      body: JSON.stringify({
        username: document.getElementById('username').value,
        password: document.getElementById('password').value,
      }),
    });
    showDashboard(data.username);
    err.classList.add('hidden');
  } catch (ex) {
    err.textContent = 'Invalid credentials';
    err.classList.remove('hidden');
  }
});

document.getElementById('logout-btn').addEventListener('click', async () => {
  await api('/auth/logout', { method: 'POST' });
  showLogin();
});

function setAiScanButtonsRunning(running) {
  const label = running ? 'AI scan running...' : 'Run AI Scan';
  for (const id of ['btn-ai-scan', 'btn-ai-scan-panel']) {
    const btn = document.getElementById(id);
    if (!btn) continue;
    btn.disabled = running;
    btn.textContent = label;
  }
}

async function startAiScan() {
  const body = scopeBody();
  const result = await api('/api/intelligence/scan', { method: 'POST', body: JSON.stringify(body) });
  if (!result.success && result.status === 'busy') {
    alert(result.message || 'AI scan already running');
    return false;
  }
  setAiScanButtonsRunning(true);
  return true;
}

document.getElementById('btn-ai-scan').addEventListener('click', async () => {
  try {
    await startAiScan();
  } catch (ex) {
    alert(ex.message || 'Failed to start AI scan');
    setAiScanButtonsRunning(false);
  }
});

document.getElementById('btn-ai-scan-panel').addEventListener('click', async () => {
  try {
    await startAiScan();
  } catch (ex) {
    alert(ex.message || 'Failed to start AI scan');
    setAiScanButtonsRunning(false);
  }
});

document.getElementById('btn-refresh').addEventListener('click', loadAll);

document.getElementById('btn-backup-all').addEventListener('click', async () => {
  const btn = document.getElementById('btn-backup-all');
  btn.disabled = true;
  btn.textContent = 'Starting...';
  try {
    const body = scopeBody();
    const result = await api('/api/backup/trigger', { method: 'POST', body: JSON.stringify(body) });
    if (!result.success && result.status === 'busy') {
      alert(result.message || 'Backup already running');
    } else {
      btn.textContent = 'Backup running...';
    }
  } catch (ex) {
    alert(ex.message || 'Failed to start backup');
    btn.disabled = false;
    btn.textContent = 'Run Backup';
  }
});

// Re-enable backup button when backup finishes (poll + websocket)
setInterval(async () => {
  const btn = document.getElementById('btn-backup-all');
  if (!btn.disabled) return;
  try {
    const status = await api('/api/backup/status');
    if (!status.running) {
      btn.disabled = false;
      btn.textContent = 'Run Backup';
      await Promise.all([loadStats(), loadTriage()]);
    }
  } catch { /* ignore */ }
}, 3000);

// Re-enable AI scan buttons when scan finishes
setInterval(async () => {
  const btn = document.getElementById('btn-ai-scan');
  if (!btn || !btn.disabled) return;
  try {
    const status = await api('/api/intelligence/status');
    if (!status.running) {
      setAiScanButtonsRunning(false);
      await loadSuggestions();
    }
  } catch { /* ignore */ }
}, 3000);

document.getElementById('btn-flag-selected').addEventListener('click', async () => {
  const ids = [...document.querySelectorAll('.dup-cb:checked')].map(c => +c.value);
  if (!ids.length) return alert('Select duplicates first');
  await api('/api/cleanup/execute', { method: 'POST', body: JSON.stringify({ duplicate_ids: ids }) });
  await loadDuplicates();
});

document.getElementById('btn-flag-large').addEventListener('click', async () => {
  const ids = [...document.querySelectorAll('.large-cb:checked')].map(c => +c.value);
  if (!ids.length) return alert('Select large emails first');
  await api('/api/cleanup/flag-large', { method: 'POST', body: JSON.stringify({ message_ids: ids }) });
  await Promise.all([loadLargeEmails(), loadStats()]);
});

document.getElementById('btn-approve-suggestions').addEventListener('click', async () => {
  const ids = [...document.querySelectorAll('.sug-cb:checked')].map(c => +c.value);
  if (!ids.length) return alert('Select suggestions first');
  if (!confirm('Flag selected suggestions on the mail server? Local backups are kept — use Empty Deleted Queue to purge later.')) return;
  const result = await api('/api/cleanup/approve', { method: 'POST', body: JSON.stringify({ suggestion_ids: ids }) });
  if (result.failed) {
    const errors = (result.results || []).filter(r => !r.success).map(r => r.error).filter(Boolean);
    alert(`Flagged ${result.flagged}, failed ${result.failed}${errors.length ? ':\n' + errors.slice(0, 3).join('\n') : ''}`);
  }
  await loadSuggestions();
});

document.getElementById('btn-expunge').addEventListener('click', async () => {
  const mailbox_id = +document.getElementById('expunge-mailbox').value;
  if (!confirm('Permanently expunge deleted messages from server?')) return;
  await api('/api/cleanup/expunge', { method: 'POST', body: JSON.stringify({ mailbox_id }) });
  await Promise.all([loadDuplicates(), loadLargeEmails()]);
});

document.getElementById('domain-form').addEventListener('submit', async (e) => {
  e.preventDefault();
  await api('/api/domains', {
    method: 'POST',
    body: JSON.stringify({
      name: document.getElementById('domain-name').value,
      imap_host: document.getElementById('domain-imap').value,
    }),
  });
  e.target.reset();
  document.getElementById('domain-imap').value = 'imap.hostinger.com';
  await loadAll();
});

document.getElementById('mailbox-email').addEventListener('input', resetMailboxValidation);
document.getElementById('mailbox-password').addEventListener('input', resetMailboxValidation);
document.getElementById('mailbox-domain').addEventListener('change', resetMailboxValidation);

document.getElementById('btn-test-connection').addEventListener('click', async () => {
  const btn = document.getElementById('btn-test-connection');
  const email = document.getElementById('mailbox-email').value;
  const password = document.getElementById('mailbox-password').value;
  const domain_id = +document.getElementById('mailbox-domain').value;

  if (!email || !password || !domain_id) {
    setValidationMessage(false, 'Enter domain, email, and password first');
    return;
  }

  btn.disabled = true;
  btn.textContent = 'Testing...';
  try {
    const result = await api('/api/mailboxes/validate', {
      method: 'POST',
      body: JSON.stringify({ domain_id, email, password }),
    });
    setValidationMessage(result.valid, result.message);
  } catch (ex) {
    setValidationMessage(false, ex.message || 'Connection test failed');
  } finally {
    btn.disabled = false;
    btn.textContent = 'Test Connection';
  }
});

document.getElementById('mailbox-form').addEventListener('submit', async (e) => {
  e.preventDefault();
  if (!mailboxValidated) {
    setValidationMessage(false, 'Test connection successfully before adding the mailbox');
    return;
  }
  const btn = document.getElementById('btn-add-mailbox');
  btn.disabled = true;
  try {
    const result = await api('/api/mailboxes', {
      method: 'POST',
      body: JSON.stringify({
        domain_id: +document.getElementById('mailbox-domain').value,
        email: document.getElementById('mailbox-email').value,
        password: document.getElementById('mailbox-password').value,
      }),
    });
    setValidationMessage(true, result.message || 'Mailbox added');
    e.target.reset();
    resetMailboxValidation();
    await loadAll();
  } catch (ex) {
    setValidationMessage(false, ex.message || 'Failed to add mailbox');
  } finally {
    btn.disabled = !mailboxValidated;
  }
});

document.getElementById('btn-cancel-edit').addEventListener('click', closeEditModal);

document.getElementById('btn-test-edit-connection').addEventListener('click', async () => {
  const email = document.getElementById('edit-mailbox-email').value;
  const password = document.getElementById('edit-mailbox-password').value;
  const domain_id = +document.getElementById('edit-mailbox-domain').value;
  const mailboxId = +document.getElementById('edit-mailbox-id').value;
  const mb = allMailboxes.find(m => m.id === mailboxId);

  if (!email || !domain_id) {
    setEditValidationMessage(false, 'Enter domain and email');
    return;
  }

  const btn = document.getElementById('btn-test-edit-connection');
  btn.disabled = true;
  btn.textContent = 'Testing...';
  try {
    if (password) {
      const result = await api('/api/mailboxes/validate', {
        method: 'POST',
        body: JSON.stringify({ domain_id, email, password }),
      });
      setEditValidationMessage(result.valid, result.message);
    } else {
      setEditValidationMessage(true, 'Password unchanged — will re-validate on save');
    }
  } catch (ex) {
    setEditValidationMessage(false, ex.message || 'Connection test failed');
  } finally {
    btn.disabled = false;
    btn.textContent = 'Test Connection';
  }
});

document.getElementById('edit-mailbox-form').addEventListener('submit', async (e) => {
  e.preventDefault();
  const mailboxId = +document.getElementById('edit-mailbox-id').value;
  const body = {
    domain_id: +document.getElementById('edit-mailbox-domain').value,
    email: document.getElementById('edit-mailbox-email').value,
  };
  const password = document.getElementById('edit-mailbox-password').value;
  if (password) body.password = password;

  const btn = document.getElementById('btn-save-edit');
  btn.disabled = true;
  try {
    await api(`/api/mailboxes/${mailboxId}`, { method: 'PUT', body: JSON.stringify(body) });
    closeEditModal();
    await loadAll();
  } catch (ex) {
    setEditValidationMessage(false, ex.message || 'Failed to update mailbox');
  } finally {
    btn.disabled = false;
  }
});

document.getElementById('large-select-all').addEventListener('change', (e) => {
  document.querySelectorAll('.large-cb:not(:disabled)').forEach(c => c.checked = e.target.checked);
});

document.getElementById('dup-select-all').addEventListener('change', (e) => {
  document.querySelectorAll('.dup-cb').forEach(c => c.checked = e.target.checked);
});

document.getElementById('sug-select-all').addEventListener('change', (e) => {
  document.querySelectorAll('.sug-cb').forEach(c => c.checked = e.target.checked);
});

let restoreOffset = 0;
const RESTORE_LIMIT = 100;
let restoreTotal = 0;

function restoreListQuery() {
  const params = new URLSearchParams();
  if (selectedTriageMailboxId) params.set('mailbox_id', selectedTriageMailboxId);
  else if (selectedDomainId) params.set('domain_id', selectedDomainId);
  const q = document.getElementById('restore-search')?.value?.trim();
  if (q) params.set('q', q);
  params.set('limit', String(RESTORE_LIMIT));
  params.set('offset', String(restoreOffset));
  return `?${params.toString()}`;
}

async function loadRestorable() {
  const tbody = document.getElementById('restore-body');
  const countEl = document.getElementById('restore-count');
  const statusEl = document.getElementById('restore-status-label');
  const prevBtn = document.getElementById('btn-restore-prev');
  const nextBtn = document.getElementById('btn-restore-next');
  if (!tbody) return;

  try {
    const data = await api('/api/messages/restorable' + restoreListQuery());
    restoreTotal = data.total || 0;
    const items = data.items || [];
    countEl.textContent = restoreTotal
      ? `Showing ${restoreOffset + 1}–${Math.min(restoreOffset + items.length, restoreTotal)} of ${restoreTotal}`
      : 'No backed-up messages';
    statusEl.textContent = selectedTriageMailboxId
      ? 'Restoring uploads each selected .eml into its original folder on the mail server.'
      : 'Tip: filter by mailbox in Triage to restore one account at a time.';
    tbody.innerHTML = items.length ? items.map(m => `
      <tr class="border-t border-slate-700">
        <td class="p-2"><input type="checkbox" class="restore-cb" value="${m.id}" data-size="${m.size || 0}"></td>
        <td class="p-2 whitespace-nowrap">${m.mailbox_email || ''}</td>
        <td class="p-2 whitespace-nowrap text-slate-400">${m.folder || ''}</td>
        <td class="p-2 truncate max-w-xs" title="${m.subject || ''}">${(m.subject || '(no subject)').slice(0, 40)}</td>
        <td class="p-2 text-slate-400 whitespace-nowrap">${formatDate(m.date)}</td>
        <td class="p-2 text-right">${formatBytes(m.size)}</td>
      </tr>
    `).join('') : '<tr><td colspan="6" class="p-4 text-center text-slate-500">No restorable messages — run backup first</td></tr>';

    prevBtn.disabled = restoreOffset <= 0;
    nextBtn.disabled = restoreOffset + RESTORE_LIMIT >= restoreTotal;
    document.getElementById('restore-select-all').checked = false;
  } catch (ex) {
    tbody.innerHTML = `<tr><td colspan="6" class="p-4 text-center text-red-400">${ex.message || 'Failed to load'}</td></tr>`;
  }
}

function selectedRestoreIds() {
  return [...document.querySelectorAll('.restore-cb:checked')].map(c => +c.value);
}

function setImportButtonsRunning(running) {
  const label = running ? 'Restoring...' : 'Restore Selected';
  const previewLabel = running ? 'Restore running...' : 'Preview Selected';
  for (const [id, text] of [['btn-import-run', label], ['btn-import-preview', previewLabel]]) {
    const btn = document.getElementById(id);
    if (!btn) continue;
    btn.disabled = running;
    btn.textContent = text;
  }
}

function showRestoreWarning(lines) {
  const el = document.getElementById('restore-warning');
  if (!el) return;
  if (!lines || !lines.length) {
    el.classList.add('hidden');
    el.textContent = '';
    return;
  }
  el.textContent = lines.join(' ');
  el.classList.remove('hidden');
}

document.getElementById('restore-select-all')?.addEventListener('change', (e) => {
  document.querySelectorAll('.restore-cb').forEach(c => c.checked = e.target.checked);
});

document.getElementById('btn-restore-search')?.addEventListener('click', () => {
  restoreOffset = 0;
  loadRestorable();
});

document.getElementById('restore-search')?.addEventListener('keydown', (e) => {
  if (e.key === 'Enter') {
    e.preventDefault();
    restoreOffset = 0;
    loadRestorable();
  }
});

document.getElementById('btn-restore-prev')?.addEventListener('click', () => {
  restoreOffset = Math.max(0, restoreOffset - RESTORE_LIMIT);
  loadRestorable();
});

document.getElementById('btn-restore-next')?.addEventListener('click', () => {
  restoreOffset += RESTORE_LIMIT;
  loadRestorable();
});

document.getElementById('btn-import-preview')?.addEventListener('click', async () => {
  const ids = selectedRestoreIds();
  if (!ids.length) return alert('Select messages to preview');
  try {
    const preview = await api('/api/import/preview', {
      method: 'POST',
      body: JSON.stringify({ message_ids: ids }),
    });
    const lines = [
      `${preview.restorable} restorable, ${preview.skipped} skipped.`,
      `About ${formatBytes(preview.total_bytes)} will be uploaded.`,
      ...(preview.warnings || []),
    ];
    showRestoreWarning(lines);
  } catch (ex) {
    alert(ex.message || 'Preview failed');
  }
});

document.getElementById('btn-import-run')?.addEventListener('click', async () => {
  const ids = selectedRestoreIds();
  if (!ids.length) return alert('Select messages to restore');
  try {
    const preview = await api('/api/import/preview', {
      method: 'POST',
      body: JSON.stringify({ message_ids: ids }),
    });
    if (!preview.restorable) {
      showRestoreWarning(preview.warnings || ['Nothing restorable in selection']);
      return alert('No restorable messages in selection');
    }
    const warn = [
      `Restore ${preview.restorable} message(s) (~${formatBytes(preview.total_bytes)}) to their original folders on the mail server?`,
      'Messages already present (same Message-ID) will be skipped.',
      'This uses Hostinger mailbox quota.',
      ...(preview.warnings || []),
    ].join('\n\n');
    if (!confirm(warn)) return;

    showRestoreWarning([
      `Starting restore of ${preview.restorable} message(s) (~${formatBytes(preview.total_bytes)}).`,
      ...(preview.warnings || []),
    ]);
    const result = await api('/api/import/trigger', {
      method: 'POST',
      body: JSON.stringify({ message_ids: ids }),
    });
    if (!result.success) {
      alert(result.message || 'Failed to start restore');
      return;
    }
    setImportButtonsRunning(true);
  } catch (ex) {
    alert(ex.message || 'Failed to start restore');
    setImportButtonsRunning(false);
  }
});

setInterval(async () => {
  const btn = document.getElementById('btn-import-run');
  if (!btn || !btn.disabled) return;
  try {
    const status = await api('/api/import/status');
    if (!status.running) {
      setImportButtonsRunning(false);
      const skipLines = (status.skipped_details || []).slice(0, 5).map(d =>
        `Skipped: [${d.folder || '?'}] ${(d.subject || '(no subject)').slice(0, 40)} — ${d.reason}`
      );
      showRestoreWarning([
        `Restore finished: imported ${status.imported || 0}, skipped ${status.skipped_existing || 0}, failed ${status.failed || 0}.`,
        ...skipLines,
        (status.skipped_details || []).length > 5
          ? `… and ${status.skipped_details.length - 5} more — see Live Log`
          : (status.skipped_existing ? 'See Live Log for full skip details.' : ''),
      ].filter(Boolean));
      await loadRestorable();
    } else {
      document.getElementById('restore-status-label').textContent =
        `Restoring… imported ${status.imported || 0}/${status.total || 0} (skipped ${status.skipped_existing || 0}, failed ${status.failed || 0})`;
    }
  } catch { /* ignore */ }
}, 3000);

// Init
(async () => {
  try {
    const me = await api('/auth/me');
    showDashboard(me.username);
  } catch {
    showLogin();
  }
})();
