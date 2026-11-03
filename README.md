> **Public portfolio sample** from [Chief Web Services](https://ChiefWebs.co.ke). Local-only email archive demo with AES credential vault and verified backup-before-delete. No production mailboxes or secrets are included.
# ChiefMailVault

**Chief Web Services** â€” Email backup, archiving, and mailbox cleanup tool.

ChiefMailVault helps you save mailbox space on Hostinger by backing up emails locally, copying them to cloud storage, and safely removing duplicate or unnecessary messages â€” only after you approve each step.

---

## What it does

- **Backs up your emails** â€” Downloads new messages from your mailboxes and saves them as standard `.eml` files (openable in Outlook, Thunderbird, Apple Mail, etc.)
- **Keeps attachments** â€” Attachments are saved inside each email file and also copied to a separate folder for easy access
- **Finds duplicates** â€” Spots the same email sitting in both Inbox and Sent (common when you CC yourself) and flags them for cleanup
- **Suggests cleanups** â€” Can recommend old newsletters, alerts, and large emails to review (optional AI feature)
- **Never deletes without your OK** â€” Nothing is permanently removed from the server until you review and confirm

---

## Before you start

You need:

1. **Windows** with **Python 3.10 or newer** installed ([python.org](https://www.python.org/downloads/))
2. Your **Hostinger email address and password** for each mailbox you want to back up
3. (Optional) Google Drive, Dropbox, or a shared folder for extra backup copies

---

## Starting the app

1. Open **PowerShell**
2. Go to the ChiefMailVault folder:

   ```powershell
   cd "path\to\chiefmailvault"
   ```

3. Run the start script:

   ```powershell
   .\start.ps1
   ```

   The first run may take a minute while it sets things up. When ready, you will see a message with the app address.

4. Open your browser and go to the URL shown in the terminal (usually **http://127.0.0.1:8088**)

   If port 8088 is blocked, the script automatically tries **18088** and prints the correct URL.

5. To stop the app, press **Ctrl+C** in the PowerShell window, or run `.\stop.ps1` from another terminal.

> **Script blocked?** If Windows warns about running scripts, run this once:
> `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`

### Running tests (before updates)

After making code changes, verify everything still works:

```powershell
.\test.ps1
```

All tests should pass before you use or share an updated build.

---

## Logging in

| Field    | Default value |
|----------|---------------|
| Username | `admin`       |
| Password | `admin123`    |

**Change these before regular use.** Open the `.env` file in the ChiefMailVault folder and edit:

- `CMV_ADMIN_USER` â€” your preferred username  
- `CMV_ADMIN_PASSWORD` â€” your preferred password  

Restart the app after saving changes.

---

## Quick start guide

### Step 1 â€” Add your domain

Scroll to **Settings** at the bottom of the dashboard.

1. Under **Add Domain**, enter your website domain (e.g. `yourcompany.com`)
2. Leave the mail server as `imap.hostinger.com` unless Hostinger gave you a different address
3. Click **Add Domain**

### Step 2 â€” Add a mailbox

1. Select your domain from the dropdown
2. Enter the full email address (e.g. `info@yourcompany.com`)
3. Enter the mailbox password
4. Click **Test Connection** â€” wait for a green success message
5. Click **Add Mailbox** (only enabled after a successful test)

If the test fails, check your email and password in Hostinger webmail. The mailbox is not saved until the connection test passes.

Passwords are stored encrypted on your computer. They are never shown in full on screen.

### Step 3 â€” Run your first backup

Click **Run Backup** near the top of the dashboard.

Watch the **Live Log** panel â€” it shows progress as emails are downloaded. Only new messages are fetched each time, so later backups are faster.

### Step 4 â€” Review duplicates (if any)

If the same email exists in both Inbox and Sent, it appears in the **Duplicates** table.

1. Tick the rows you want to clean up
2. Click **Flag for Deletion** â€” this marks them on the server but does not remove them yet
3. Select the mailbox in **Expunge Queue**
4. Click **Empty Deleted Queue** â€” this permanently removes flagged messages from Hostinger

Both copies are kept in your local backup before anything is deleted from the server.

---

## Dashboard overview

| Section | What it shows |
|---------|---------------|
| **Metrics** | How many domains, mailboxes, messages, duplicates, and large emails you have |
| **Run Backup** | Download new emails now |
| **Live Log** | Real-time activity feed |
| **Duplicates** | Inbox/Sent copies of the same email â€” safe cleanup candidates |
| **Cleanup Suggestions** | Recommended emails to review (newsletters, old alerts, etc.) |
| **Expunge Queue** | Final step to permanently clear flagged messages from the server |
| **Settings** | Add domains and mailboxes |

---

## Where your backups are saved

All data is stored in the `chiefmailvault_data` folder inside ChiefMailVault:

```
chiefmailvault_data/
â”œâ”€â”€ storage/          â† Your email backups (.eml files and attachments)
â””â”€â”€ uploads/          â† Zip files prepared for cloud upload
```

Emails are organised by domain, account, year, and month â€” for example:

`storage/yourcompany.com/info_at_yourcompany/2026/06_June/email_10214.eml`

You can copy these files to another drive or import them into any email program that supports `.eml` files.

---

## Automatic backups

By default, ChiefMailVault checks for new mail every **6 hours** while the app is running. You can change this in `.env`:

`CMV_SYNC_INTERVAL_HOURS=6`

---

## Optional: Cloud backup

To also copy backups to Google Drive, Dropbox, or a shared network folder, edit the `.env` file:

| Setting | Purpose |
|---------|---------|
| `CMV_DRIVE_ENABLED=true` | Upload to Google Drive |
| `CMV_DROPBOX_ENABLED=true` | Upload to Dropbox |
| `CMV_NAS_ENABLED=true` | Copy to a local/shared folder |

Set `CMV_NAS_PATH` to your shared folder path (e.g. `D:\Backups\Email`).

Cloud setup details are in `.env.example`. Ask your IT contact if you need help with Google or Dropbox credentials.

---

## Optional: Smart cleanup suggestions

If you have **Ollama** running on your computer (a local AI tool), ChiefMailVault can suggest emails to clean up based on subject, sender, date, and folder â€” **metadata only**, never full email bodies.

In `.env`, set:

```
CMV_OLLAMA_ENABLED=true
CMV_OLLAMA_URL=http://localhost:11434
CMV_OLLAMA_MODEL=phi3:mini
```

Pull the model first: `ollama pull phi3:mini` (or whatever model you configure).

Click **Run AI Scan** anytime (even during backup). Suggestions show mailbox, subject, sender, date, folder, and size so you can decide what to approve.

### Cleanup categories

| Category | Definition | Rule-based criteria |
|---|---|---|
| **Bloated thread** | An older message in a long email conversation where a newer message exists with the same topic | 2+ messages share the same normalized subject (ignoring `Re:` / `Fwd:` prefixes). All except the **newest** are suggested. |
| **Large attachment** | Email already archived locally but still taking server space | Size greater than 25 MB |
| **Newsletter clutter** | Old marketing/digest mail | Sender or subject matches newsletter keywords and message is older than 14 days |
| **System notifications** | Old automated alerts | Sender/subject matches alert keywords and message is older than 30 days |

#### What is a â€œbloatedâ€ email?

A **bloated thread** message is not judged by file size alone. It is an **older reply or forward** in a conversation chain â€” for example, five versions of â€œRE: Contract reviewâ€ where you only need the latest. ChiefMailVault groups messages by subject (stripping `Re:`/`Fwd:`), keeps the newest, and suggests removing the rest **after** they are safely backed up.

With Ollama enabled, the local AI applies the same categories using metadata snippets. If Ollama is offline or the model is missing, rule-based detection is used automatically.

Suggestions appear in the **AI Cleanup Suggestions** panel. Nothing is deleted automatically â€” you tick items and approve them yourself.

---

## Safety rules (built in)

ChiefMailVault is designed to protect your data:

- Emails are **fully backed up and verified** before anything is removed from Hostinger
- Deletion is **two steps**: flag first, then expunge when you are ready
- Passwords and API keys are **masked** on screen
- Emails larger than **25 MB** are highlighted so you can review them
- Cleanup suggestions are **recommendations only** â€” you always have the final say

---

## Common questions

**The app won't start â€” "port already in use"**  
Run `.\stop.ps1` first, then `.\start.ps1` again. If port 8088 is stuck (ghost listener), the script will automatically use port **18088** â€” check the URL printed in the terminal.

**Site won't load / page spins forever**  
A previous session may still be holding the port. Run `.\stop.ps1`, then `.\start.ps1`. Use the exact URL shown in the terminal (may be **18088** if 8088 is blocked).

**Duplicates table is empty**  
Duplicates only appear when the same email exists in both Inbox and Sent. Not all mailboxes have these.

**I flagged emails but they're still in webmail**  
Flagging marks them for deletion. You must click **Empty Deleted Queue** to permanently remove them.

**How do I restore an email?**  
Use **Restore to Server** in the dashboard: select messages, preview (shows size/quota warning), then restore. Each message goes back to its **original folder**. If the same Message-ID already exists on the server, it is skipped. You can still open `.eml` files from `chiefmailvault_data/storage` in Thunderbird/Outlook if you prefer.

**How do I know backups are safe to delete from the server?**  
After every backup, ChiefMailVault runs an **integrity audit** (file exists + MD5). Each mailbox shows `N/N restore-ready`. Use **Verify Backups** to re-check anytime, then **Flag Verified** to mark those messages for deletion on Hostinger (still requires **Empty Deleted Queue** to purge).

**Integrity fails with MD5 mismatch on many UIDs**  
IMAP UIDs are unique **per folder**. Older builds stored `email_{uid}.eml` without the folder name, so Sent could overwrite Inbox for the same UID. Current builds store under `.../{year}/{month}/{folder}/email_{uid}.eml`. **Verify Backups** re-fetches failed messages onto the correct paths.

---

## Getting help

For technical specifications and development details, see:

- `ChiefMailVault Specifications.md`
- `BUILD_INSTRUCTIONS.md`

For day-to-day use, this README is your main guide.

---

*ChiefMailVault â€” Chief Web Services*
