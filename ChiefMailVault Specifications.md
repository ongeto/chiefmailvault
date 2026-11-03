# **Product Specification Document (PSD)**

## **Project Name: ChiefMailVault**

**Brand:** Chief Web Services (CWS)

**Document Version:** 1.1.0

**Author:** Chief Web Services Engineering Team

**Status:** Ready for Implementation (Updated)

## **1\. Executive Summary**

**ChiefMailVault** is a secure, automated, multi-tenant email archiving, backup, and mailbox optimization system designed as an in-house utility for Chief Web Services and its clients to combat rapid storage saturation.

Unlike standard static archiving tools, ChiefMailVault not only aggregates and backups emails with attachments to universal standard formats (.eml) and mirrors them to zero-cost cloud providers (such as Google Drive's 15GB free tier), but it also actively optimizes mailbox space. Utilizing a specialized cleanup system, the tool identifies and purges duplicate messages (such as identical emails sitting in both Inbox and Sent folders) directly from Hostinger's mail servers. Optionally, an embedded **Local GPT Intelligence Engine** scans metadata patterns to recommend cleanups of newsletters, alerts, and bloated message chains, keeping mailboxes lean and lightweight.

## **2\. Core Architecture & Pipeline**

\+-------------------------------------------------------------+  
|                     ChiefMailVault Web UI                   |  
|  (User Authentication, Multi-Domain Settings, Stat Counters, |  
|   Interactive Clean-up Suggestions Panel, Execution Logs)   |  
\+------------------------------+------------------------------+  
                               | API / Controller Calls  
                               v  
\+-------------------------------------------------------------+  
|                System Orchestration Layer                   |  
| (Python Scheduler / SQLite Metadata Sync / Multi-threading) |  
\+------------------------------+------------------------------+  
         |                     |                      |  
         | Raw Emails          | Local Metadata       | Cleanup Directives  
         v                     v                      v  
\+----------------+     \+---------------+      \+---------------+  
| Parser Engine  |     |   Local GPT   |      |  IMAP Clean   |  
| (.eml / .mbox) |     | Scan Engine   |      |  & Purge      |  
|                |     | (Local LLM)   |      |  (Expunge)    |  
\+--------+-------+     \+-------+-------+      \+-------+-------+  
         |                     |                      |  
         v Local Sync          v Recommended Actions  v Hostinger Delete  
\+--------------+       \+---------------+      \+---------------+  
| Local System |       |  Interactive  |      | Hostinger IMAP|  
| File Storage |       | Clean-up list |      | Mail Servers  |  
\+------+-------+       \+---------------+      \+---------------+  
       | Mirroring  
       v  
\+--------------+  
| Cloud Storage|  
| (Google Drive|  
| / Dropbox)   |  
\+--------------+

## **3\. Detailed Feature Requirements**

### **3.1 Multi-Domain Configuration Engine**

* **Decoupled Host Accounts:** The system reads configuration profiles for multiple domains and user accounts from a secure, local configuration database (SQLite).  
* **Mailbox Mapping:** Each domain configuration supports multiple sub-accounts (e.g., info@domain-a.com, billing@domain-a.com, sales@domain-b.com).  
* **Secure Credential Vaulting:** Account passwords are encrypted at rest using AES-256 (via Python's cryptography library) and decrypted only in-memory during active IMAP connections.

### **3.2 Backup Mechanics & Universal Compatibility**

* **IMAP Incremental Syncing:** To preserve bandwidth, the backup process queries the local database cache to index existing downloaded message IDs (UIDs) and only pulls newly arrived messages.  
* **RFC822 Message Output:** Emails are written as raw .eml files. This maintains universal standard formatting preserving styling, headers, MIME structures, and attachments.  
* **Attachment Preservation:** Attachments remain embedded inside the .eml file, and are also extracted to an external directory (/backups/{domain}/{account}/{year}/{month}/attachments/) for independent, direct access.  
* **Import Compatibility:** Because .eml is globally recognized, backups are immediately importable into clients such as Thunderbird, Outlook, and Apple Mail via standard folder imports.

### **3.3 Zero-Cost Cloud Storage Integrations**

The system routes compiled archival folders to zero-cost cloud environments:

1. **Google Drive (Primary):**  
   * *Allocation:* 15 GB free tier.  
   * *Process:* Compiles mailbox backups into timestamps zips ({domain\_mailbox}\_backup\_{timestamp}.zip) and uploads them to configured directories via Google Workspace Drive API v3.  
2. **Dropbox (Secondary):**  
   * *Allocation:* 2 GB free tier.  
   * *Process:* Automated sync via the Dropbox HTTP v2 API.  
3. **Local Network Mirror:**  
   * Direct folder mirroring to local Network Attached Storage (NAS) or shared directory mounts.

### **3.4 User-Session-Controlled Web Panel**

The web interface is powered by a fast web framework (FastAPI) and provides a secure dashboard:

* **Session Access Control:** Administrator logins are protected via cryptographically signed JWT tokens and secure HTTP-only cookies.  
* **Dashboard UI Components:**  
  * **Domain & Mailbox Metrics:** Live statistics displaying cumulative storage space, message count, duplicate counts, and last backup operations.  
  * **Active Logging Console:** An asynchronous log terminal outputting active sync and cleanup status updates.  
  * **GPT Intelligence Feed:** An interface showcasing auto-generated space optimization tips and cleanup tables.  
  * **Interactive Clean-up Tool:** Grid interfaces displaying flagged emails. Administrators can toggle checkboxes and execute bulk purges with a single click.

### **3.5 Deduplication & Clean-up Engine (NEW)**

To prevent mailbox quotas from reaching maximum capacity, ChiefMailVault implements automated server-side space recovery mechanisms.

* **The Self-Sent (Inbox/Sent) Duplicate Detector:**  
  * When a user sends an email to themselves or CCs/BCCs their own address, the message is stored twice on Hostinger's servers (once in the "Sent" folder, once in the "Inbox" folder).  
  * The tool logs the Message-ID header of every downloaded email. If duplicate Message-IDs are matched across both the INBOX and Sent mailboxes for a single user, they are flagged as safe-to-clean duplicates.  
  * The engine retains the local .eml backup copies of both instances (to ensure historical context is kept in full archive logs) but selects the server-side INBOX instance for deletion to free up active server quota.  
* **IMAP Delete-and-Purge Lifecycle:**  
  * Deleting emails via standard IMAP requires a two-step handshake to ensure data safety:  
    1. **Mark for Deletion:** The system selects the target mailbox and flags target email numbers or UIDs: imap.store(UID, "+FLAGS", "\\\\Deleted").  
    2. **Expunge:** The system executes imap.expunge() to permanently flush flagged messages from Hostinger's email server storage.  
  * *Safety Guard:* Before any server-side deletion is executed, the tool verifies that a complete .eml copy of the target email is safely written and verified in both local file storage and mirrored cloud environments.

### **3.6 Local GPT Intelligence Engine (NEW)**

An optional, offline machine learning workflow enhances cleanup efficiency by analyzing message metadata without violating data privacy or incurring usage fees.

* **Local Inference Integration:**  
  * The system exposes a configurable connection to a local LLM runner (such as Ollama or Llama.cpp running a lightweight model like Llama-3-8B-Instruct or Phi-3-Mini on the local machine).  
  * If enabled, the system bypasses cloud APIs entirely, avoiding external subscription fees and keeping sensitive company email contents completely private.  
* **Header & Structural Processing:**  
  * The script extracts raw metadata from the local SQLite index (Sender, Subject, Mailbox, Size, Date, Content-Type, and a short 100-character snippet).  
  * **It never sends raw, full-body email archives to the LLM.** Only structural metadata tables are analyzed.  
* **Target Classification Categories:**  
  * The Local GPT is prompted to classify emails into the following actionable categories:  
    1. **System Notifications & Alerts:** Automated logs, crontabs, or build reports that are older than 30 days.  
    2. **Newsletter Clutter:** Mass subscription feeds that have remained unread for more than 14 days.  
    3. **Bloated Threads:** Extremely long back-and-forth chains where only the latest email is necessary to keep (as it contains all quoted preceding context).  
    4. **Large Attachment Outliers:** Safe candidates where attachments have been successfully archived locally but the active online copy can be purged to save space.  
* **Drafting Cleanup Rules:**  
  * The local GPT generates an index of recommended cleanup actions. These appear inside the Web Panel as a proposed "Cleanup Plan." No items are automatically deleted; administrators must review and approve suggestions before they are executed.

## **4\. Technical Stack Recommendation**

| Component | Technology / Library | Reason |
| :---- | :---- | :---- |
| **Language** | Python 3.10+ | Robust library ecosystems for IMAP, parsing, and local AI API clients. |
| **Database** | SQLite 3 | Lightweight, serverless, relational storage; indexes email hashes for duplicates. |
| **Web Server** | FastAPI / Uvicorn | High-performance asynchronous execution; optimal for keeping UI logs responsive. |
| **Frontend UI** | HTML5, Tailwind CSS, JS (AJAX) | Responsive single-page interface with real-time stats and cleanup approvals. |
| **IMAP Layer** | imaplib \+ email (Built-in) | Controls two-step IMAP connection, flag management, and server purging. |
| **Local AI Client** | httpx / Ollama API | Communicates asynchronously with locally hosted Ollama/Llama server endpoints. |
| **Cloud Uploads** | google-api-python-client | Official SDK wrapper for handling Drive API v3 requests. |
| **Security** | passlib \+ pyjwt | Restricts dashboard metrics and cleanup execution to verified admins. |

## **5\. Directory Mapping and Storage Schema**

chiefmailvault\_data/  
â”‚  
â”œâ”€â”€ config.db                  \# SQLite (stores domain configs, email UIDs, deduplication indexes)  
â”‚  
â”œâ”€â”€ storage/                   \# Local file archives (structured for easy readability)  
â”‚   â”œâ”€â”€ \[example.com/\](https://example.com/)  
â”‚   â”‚   â”œâ”€â”€ info\_at\_example/  
â”‚   â”‚   â”‚   â”œâ”€â”€ 2026/  
â”‚   â”‚   â”‚   â”‚   â”œâ”€â”€ 06\_June/  
â”‚   â”‚   â”‚   â”‚   â”‚   â”œâ”€â”€ email\_10214.eml  
â”‚   â”‚   â”‚   â”‚   â”‚   â””â”€â”€ attachments/  
â”‚   â”‚   â”‚   â”‚   â”‚       â”œâ”€â”€ invoice\_10214.pdf  
â”‚   â”‚   â”‚   â”‚   â”‚       â””â”€â”€ contract\_10214.docx  
â”‚   â”‚   â”‚   â”‚   â””â”€â”€ 07\_July/  
â”‚   â”‚   â”‚   â”‚       â””â”€â”€ ...  
â”‚   â”‚   â””â”€â”€ sales\_at\_example/  
â”‚   â””â”€â”€ \[otherdomain.com/\](https://otherdomain.com/)  
â”‚  
â””â”€â”€ uploads/                   \# Staging area for zipping before cloud transmission

## **6\. Security & Guardrails**

* **Verification Before Deletion:** The system must run a checksum validation (matching MD5 file hashes) on the downloaded .eml backups before initiating an IMAP \\Deleted flag.  
* **No "Auto-Expunge" Defaults:** The system defaults to a safe-mode state where emails are only flagged on the server, requiring a manual, UI-triggered "Empty Deleted Queue" or "Approve LLM Cleanup" step to execute a structural EXPUNGE.  
* **Credential Masking:** Plain-text passwords and cloud keys are strictly masked (\*\*\*\*\*\*\*\*) inside web panel responses.  
* **IMAP Rate Throttling:** The thread pool enforces 0.5-second sleep buffers between multi-mailbox queries to avoid Hostinger IP blacklisting or connection dropouts.  
* **File Size Guardrails:** Email sizes greater than 25MB are highlighted and can be stripped of online attachments while leaving the core text on the live mailbox.

eof  
