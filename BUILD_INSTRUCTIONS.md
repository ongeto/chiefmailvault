# ChiefMailVault — Build & Commission Instructions

Use this document as the master prompt for implementing, testing, and commissioning ChiefMailVault locally. Source of truth: `ChiefMailVault Specifications.md` v1.1.0.

---

## Mission

Build a **secure, automated, multi-tenant email archiving and mailbox optimization system** for Chief Web Services. It must:

1. Incrementally backup Hostinger mailboxes to `.eml` (+ extracted attachments)
2. Mirror backups to Google Drive, Dropbox, and/or local NAS
3. Detect and purge safe duplicates (Inbox/Sent self-sent) after verified backup
4. Optionally recommend cleanups via a **local** LLM (metadata only)
5. Expose a FastAPI admin dashboard with live logs and manual approval for all destructive actions

**Deploy target:** Local machine only. No cloud server provisioning.

---

## Phase 0 — Scaffold

```
ChiefMailVault/
├── requirements.txt
├── .env.example
├── main.py                 # uvicorn entry: app.main:app
├── app/
│   ├── main.py             # FastAPI app factory
│   ├── auth.py             # JWT + HTTP-only cookies
│   ├── routes/             # domains, mailboxes, stats, cleanup, backup
│   └── websocket.py        # live log stream
├── core/
│   ├── orchestrator.py     # scheduler, thread pool, job queue
│   └── scheduler.py        # APScheduler or asyncio periodic tasks
├── db/
│   ├── database.py         # SQLite connection + migrations
│   ├── models.py           # domains, mailboxes, messages, duplicates, cleanup_suggestions
│   └── vault.py            # AES-256 encrypt/decrypt credentials
├── imap/
│   ├── client.py           # connection wrapper, rate limiting
│   ├── sync.py             # incremental UID fetch
│   ├── dedup.py            # Message-ID cross-folder detection
│   └── purge.py            # flag + expunge lifecycle
├── parser/
│   └── eml_writer.py       # RFC822 write + attachment extraction
├── storage/
│   ├── local.py            # path builder per spec schema
│   ├── checksum.py         # MD5 verify
│   ├── drive.py            # Google Drive API v3 upload
│   ├── dropbox.py          # Dropbox v2 upload
│   └── nas.py              # local folder mirror
├── intelligence/
│   ├── ollama_client.py    # httpx async to local LLM
│   └── classifier.py       # metadata → cleanup categories
├── static/
│   ├── css/                # Tailwind build output
│   └── js/dashboard.js     # AJAX, log terminal, grids
├── templates/
│   └── index.html          # single-page dashboard
└── tests/
    ├── test_vault.py
    ├── test_eml_writer.py
    ├── test_dedup.py
    ├── test_checksum_guard.py
    └── test_api_auth.py
```

### requirements.txt (minimum)

```
fastapi>=0.110
uvicorn[standard]>=0.27
python-jose[cryptography]>=3.3
passlib[bcrypt]>=1.7
cryptography>=42
httpx>=0.27
google-api-python-client>=2.100
google-auth-oauthlib>=1.2
apscheduler>=3.10
python-multipart>=0.0.9
aiofiles>=23
pytest>=8.0
pytest-asyncio>=0.23
```

### .env.example

```
CMV_DATA_ROOT=./chiefmailvault_data
CMV_SECRET_KEY=change-me-to-random-64-char-string
CMV_ADMIN_USER=admin
CMV_ADMIN_PASSWORD_HASH=          # bcrypt via passlib
CMV_VAULT_KEY=                    # base64 Fernet key for AES credential storage
CMV_OLLAMA_URL=http://localhost:11434
CMV_OLLAMA_MODEL=phi3:mini
CMV_IMAP_HOST=imap.hostinger.com
CMV_IMAP_PORT=993
```

---

## Phase 1 — Database & Credential Vault

### SQLite schema (`config.db`)

| Table | Key columns |
|---|---|
| `domains` | id, name, imap_host, imap_port, created_at |
| `mailboxes` | id, domain_id, email, encrypted_password, last_sync_at |
| `messages` | id, mailbox_id, uid, folder, message_id, md5_hash, size, date, eml_path, cloud_synced, nas_synced |
| `duplicates` | id, mailbox_id, message_id, inbox_uid, sent_uid, status (flagged/deleted) |
| `cleanup_suggestions` | id, mailbox_id, category, message_ids (JSON), reason, approved, executed |
| `backup_jobs` | id, mailbox_id, status, started_at, finished_at, messages_added, error |
| `admin_users` | id, username, password_hash |

### Vault implementation

- Generate Fernet key on first run if `CMV_VAULT_KEY` unset; print once to console.
- `encrypt(plaintext) -> bytes`, `decrypt(ciphertext) -> str` used only in IMAP client init.

**Test:** Round-trip encrypt/decrypt; ensure DB never stores plaintext passwords.

---

## Phase 2 — IMAP Incremental Backup

### Flow per mailbox

1. Connect IMAP SSL to Hostinger (`CMV_IMAP_HOST:993`)
2. For each folder (INBOX, Sent, and configured extras):
   - SELECT folder
   - Load known UIDs from `messages` table
   - `UID SEARCH ALL` → diff → FETCH new UIDs (RFC822)
3. For each new message:
   - Parse headers → extract `Message-ID`, date, size
   - Write `.eml` to `storage/{domain}/{account}/{year}/{month}/{folder}/email_{uid}.eml`
   - Extract attachments to `attachments/` subfolder
   - Compute MD5 of `.eml` file → store in `messages`
   - Run dedup check (Phase 3)
4. `sleep(0.5)` between folder operations
5. Log progress to WebSocket buffer

### Incremental rule

Never re-fetch a UID already in `messages` for that mailbox+folder unless `force_resync` flag set.

**Test:** Mock IMAP with `imaplib` test doubles or recorded fixtures; verify only new UIDs fetched on second run.

---

## Phase 3 — Deduplication Engine

After each message indexed:

```python
if message_id exists in messages for same mailbox:
    folders = {m.folder for m in matches}
    if "INBOX" in folders and "Sent" in folders:
        insert into duplicates (status='flagged')
```

- Local `.eml` for **both** instances must be retained.
- Server deletion target: **INBOX** UID only.

**Test:** Seed DB with two messages sharing Message-ID in INBOX and Sent → duplicate row created.

---

## Phase 4 — Pre-Delete Verification & Purge

### `can_purge(message_id) -> bool`

1. All `.eml` files for that Message-ID exist on disk
2. MD5 on disk matches `messages.md5_hash`
3. `cloud_synced = 1` OR cloud disabled in config OR `nas_synced = 1`

### Purge flow (admin-approved only)

```
POST /api/cleanup/execute  { duplicate_ids: [...] }
  → for each: imap.store(inbox_uid, "+FLAGS", "\\Deleted")
  → update duplicates.status = 'flagged_deleted'
  → log "flagged, awaiting expunge"

POST /api/cleanup/expunge  { mailbox_id }
  → imap.expunge()
  → update status = 'purged'
```

**Never** call `expunge()` automatically after flagging.

**Test:** `can_purge` returns False when MD5 mismatch or cloud_synced=0; purge endpoints reject unauthenticated requests.

---

## Phase 5 — Cloud & NAS Mirroring

### Packaging

After backup job completes for a mailbox:

1. Zip `storage/{domain}/{account}/` → `uploads/{domain_mailbox}_backup_{timestamp}.zip`
2. Upload to configured destinations
3. Mark `messages.cloud_synced = 1` for messages in that archive

### Google Drive

- OAuth2 desktop flow; store refresh token encrypted in DB or `.env`
- Upload to configured folder ID via Drive API v3 `files.create`

### Dropbox

- OAuth2 or long-lived access token (encrypted)
- `files/upload` to `/{path}/{zipname}`

### NAS

- `shutil.copy2` or `robocopy` equivalent to configured UNC/local path

**Test:** Mock HTTP clients; verify zip created with correct naming convention.

---

## Phase 6 — Local GPT Intelligence (Optional)

### Enable gate

Only run if `CMV_OLLAMA_URL` reachable and admin enables per-domain.

### Input (metadata only)

```json
{
  "sender": "...",
  "subject": "...",
  "mailbox": "INBOX",
  "size_bytes": 12345,
  "date": "2026-06-01",
  "content_type": "text/html",
  "snippet": "first 100 chars of plain text"
}
```

### Classification categories

1. System notifications & alerts (>30 days old)
2. Newsletter clutter (unread >14 days)
3. Bloated threads (keep latest only)
4. Large attachment outliers (archived locally)

### Output

Insert rows into `cleanup_suggestions` with `approved=0`, `executed=0`. Display in dashboard; admin checks boxes → `/api/cleanup/execute`.

**Test:** Mock Ollama response; verify no full body in outbound HTTP payload.

---

## Phase 7 — Web Dashboard

### Pages / sections (single `index.html`)

1. **Login** — form → JWT cookie
2. **Dashboard** — metric cards per domain/mailbox
3. **Live Log** — WebSocket tail (`/ws/logs`)
4. **Duplicates** — DataTable with checkboxes + "Flag for Deletion"
5. **GPT Suggestions** — categorized table + "Approve Selected"
6. **Expunge Queue** — mailbox selector + "Empty Deleted Queue" button
7. **Settings** — add domain/mailbox, cloud config, Ollama toggle

### Styling

- Tailwind CSS (CDN for dev or `npx tailwindcss` build for prod)
- Responsive; works at 1280px+ admin viewport

**Test:** Login flow, protected route 401 without cookie, WebSocket connects.

---

## Phase 8 — Orchestration & Scheduler

- `APScheduler` or asyncio loop: configurable interval (default 6 hours) per mailbox
- Thread pool (max 3 workers) for parallel mailbox sync with global IMAP throttle
- `POST /api/backup/trigger` for on-demand run
- Job status → `backup_jobs` table + WebSocket events

---

## Phase 9 — Integration Test & Commission Checklist

Run locally:

```bash
cd ChiefMailVault
python -m venv .venv
.venv\Scripts\activate        # Windows
pip install -r requirements.txt
cp .env.example .env          # fill values
python -m pytest tests/ -v
uvicorn app.main:app --reload --host 127.0.0.1 --port 8080
```

### Commission checklist

- [ ] Admin can log in; credentials masked in UI
- [ ] Add domain + mailbox; password stored encrypted in SQLite
- [ ] Manual backup pulls new emails only (incremental verified)
- [ ] `.eml` files written to correct `storage/` path schema
- [ ] Attachments extracted to `attachments/` subdirectory
- [ ] MD5 hashes stored and verification passes
- [ ] Self-sent duplicates detected and shown in UI
- [ ] Flag-delete blocked when backup unverified
- [ ] Flag-delete succeeds when backup + cloud synced
- [ ] Expunge is separate manual action
- [ ] Google Drive OR Dropbox OR NAS upload succeeds (at least one configured)
- [ ] Ollama suggestions appear (if enabled); no full bodies sent
- [ ] IMAP throttle observable in logs (0.5s gaps)
- [ ] Emails >25 MB highlighted in UI
- [ ] Live log stream shows sync progress

---

## Agent Execution Prompt

Copy everything below into a new Cursor agent session to implement the full solution:

---

**You are building ChiefMailVault from scratch.**

Read `ChiefMailVault Specifications.md` and follow `.cursor/rules/*.mdc` in this project.

**Goal:** Implement all phases (0–9) in `BUILD_INSTRUCTIONS.md`. Deploy locally only.

**Constraints:**
- Python 3.10+, FastAPI, SQLite, imaplib, Tailwind dashboard
- Data root: `chiefmailvault_data/` per spec directory schema
- AES-256 credential vault; JWT admin auth with HTTP-only cookies
- Incremental IMAP backup to `.eml` + attachment extraction
- Message-ID dedup across INBOX/Sent; delete INBOX server copy only after MD5-verified local + cloud backup
- Two-step purge: flag via API, expunge only on explicit admin action
- 0.5s IMAP throttle between mailbox queries
- Optional Ollama integration using metadata only (never full email bodies)
- Google Drive v3, Dropbox v2, and NAS mirror support

**Order of work:**
1. Scaffold project structure and `requirements.txt`
2. SQLite schema + credential vault + admin auth
3. IMAP sync + `.eml` writer + checksums
4. Dedup engine
5. Pre-delete guards + purge lifecycle
6. Cloud/NAS upload pipeline
7. FastAPI routes + WebSocket logs
8. Tailwind dashboard (login, metrics, duplicates grid, GPT feed, expunge, settings)
9. Scheduler/orchestrator
10. pytest suite covering vault, eml, dedup, checksum guard, auth
11. Run tests; fix failures; verify commission checklist

**Do not:**
- Auto-expunge after flagging
- Delete server emails without verified backup
- Send full email bodies to LLM
- Store plaintext passwords
- Skip IMAP rate limiting

**Done when:** All commission checklist items pass, `pytest` green, app runs on `http://127.0.0.1:8080`.

---
