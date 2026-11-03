"""Database CRUD helpers."""

import json
from core.timezone_utils import now_iso
from typing import Any

from db.database import get_db


def row_to_dict(row) -> dict[str, Any] | None:
    if row is None:
        return None
    return dict(row)


def create_domain(name: str, imap_host: str, imap_port: int = 993) -> int:
    with get_db() as conn:
        cur = conn.execute(
            "INSERT INTO domains (name, imap_host, imap_port) VALUES (?, ?, ?)",
            (name, imap_host, imap_port),
        )
        return cur.lastrowid


def list_domains() -> list[dict]:
    with get_db() as conn:
        rows = conn.execute("SELECT * FROM domains ORDER BY name").fetchall()
        return [dict(r) for r in rows]


def get_domain(domain_id: int) -> dict | None:
    with get_db() as conn:
        row = conn.execute("SELECT * FROM domains WHERE id = ?", (domain_id,)).fetchone()
        return row_to_dict(row)


def create_mailbox(
    domain_id: int, email: str, encrypted_password: bytes, credentials_validated: bool = False
) -> int:
    validated_at = now_iso() if credentials_validated else None
    with get_db() as conn:
        cur = conn.execute(
            """INSERT INTO mailboxes
               (domain_id, email, encrypted_password, credentials_validated, validated_at)
               VALUES (?, ?, ?, ?, ?)""",
            (domain_id, email, encrypted_password, int(credentials_validated), validated_at),
        )
        return cur.lastrowid


def mark_mailbox_validated(mailbox_id: int, validated: bool) -> None:
    with get_db() as conn:
        conn.execute(
            """UPDATE mailboxes SET credentials_validated = ?, validated_at = ?
               WHERE id = ?""",
            (int(validated), now_iso() if validated else None, mailbox_id),
        )


def list_mailboxes(domain_id: int | None = None) -> list[dict]:
    with get_db() as conn:
        if domain_id:
            rows = conn.execute(
                """SELECT m.*, d.name as domain_name FROM mailboxes m
                   JOIN domains d ON d.id = m.domain_id
                   WHERE m.domain_id = ? ORDER BY m.email""",
                (domain_id,),
            ).fetchall()
        else:
            rows = conn.execute(
                """SELECT m.*, d.name as domain_name FROM mailboxes m
                   JOIN domains d ON d.id = m.domain_id ORDER BY m.email"""
            ).fetchall()
        return [dict(r) for r in rows]


def get_mailbox(mailbox_id: int) -> dict | None:
    with get_db() as conn:
        row = conn.execute(
            """SELECT m.*, d.name as domain_name, d.imap_host, d.imap_port
               FROM mailboxes m JOIN domains d ON d.id = m.domain_id
               WHERE m.id = ?""",
            (mailbox_id,),
        ).fetchone()
        return row_to_dict(row)


def update_mailbox(
    mailbox_id: int,
    email: str | None = None,
    domain_id: int | None = None,
    encrypted_password: bytes | None = None,
    credentials_validated: bool | None = None,
) -> bool:
    mailbox = get_mailbox(mailbox_id)
    if not mailbox:
        return False

    fields = []
    values = []
    if email is not None:
        fields.append("email = ?")
        values.append(email)
    if domain_id is not None:
        fields.append("domain_id = ?")
        values.append(domain_id)
    if encrypted_password is not None:
        fields.append("encrypted_password = ?")
        values.append(encrypted_password)
    if credentials_validated is not None:
        fields.append("credentials_validated = ?")
        values.append(int(credentials_validated))
        fields.append("validated_at = ?")
        values.append(now_iso() if credentials_validated else None)

    if not fields:
        return True

    values.append(mailbox_id)
    with get_db() as conn:
        conn.execute(
            f"UPDATE mailboxes SET {', '.join(fields)} WHERE id = ?",
            values,
        )
    return True


def delete_mailbox(mailbox_id: int) -> bool:
    with get_db() as conn:
        cur = conn.execute("DELETE FROM mailboxes WHERE id = ?", (mailbox_id,))
        return cur.rowcount > 0


def get_message_by_uid(mailbox_id: int, folder: str, uid: int) -> dict | None:
    with get_db() as conn:
        row = conn.execute(
            """SELECT * FROM messages
               WHERE mailbox_id = ? AND folder = ? AND uid = ?""",
            (mailbox_id, folder, uid),
        ).fetchone()
        return row_to_dict(row)


def update_message_storage(
    message_id: int,
    *,
    eml_path: str,
    md5_hash: str,
    size: int,
    message_id_header: str | None = None,
    date: str | None = None,
    sender: str | None = None,
    subject: str | None = None,
    content_type: str | None = None,
    snippet: str | None = None,
    is_large: bool | None = None,
) -> None:
    """Rewrite local storage fields after a re-fetch or path migration."""
    with get_db() as conn:
        row = conn.execute("SELECT * FROM messages WHERE id = ?", (message_id,)).fetchone()
        if not row:
            return
        conn.execute(
            """UPDATE messages SET
                 eml_path = ?, md5_hash = ?, size = ?,
                 message_id = ?, date = ?, sender = ?, subject = ?,
                 content_type = ?, snippet = ?, is_large = ?
               WHERE id = ?""",
            (
                eml_path,
                md5_hash,
                size,
                message_id_header if message_id_header is not None else row["message_id"],
                date if date is not None else row["date"],
                sender if sender is not None else row["sender"],
                subject if subject is not None else row["subject"],
                content_type if content_type is not None else row["content_type"],
                snippet if snippet is not None else row["snippet"],
                int(is_large) if is_large is not None else row["is_large"],
                message_id,
            ),
        )


def list_mailbox_messages(mailbox_id: int) -> list[dict]:
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM messages WHERE mailbox_id = ? ORDER BY folder, uid",
            (mailbox_id,),
        ).fetchall()
        return [dict(r) for r in rows]


def list_integrity_failed_messages(mailbox_id: int) -> list[dict]:
    with get_db() as conn:
        rows = conn.execute(
            """SELECT * FROM messages
               WHERE mailbox_id = ? AND (integrity_ok = 0 OR integrity_ok IS NULL)
               ORDER BY folder, uid""",
            (mailbox_id,),
        ).fetchall()
        return [dict(r) for r in rows]


def get_known_uids(mailbox_id: int, folder: str) -> set[int]:
    with get_db() as conn:
        rows = conn.execute(
            "SELECT uid FROM messages WHERE mailbox_id = ? AND folder = ?",
            (mailbox_id, folder),
        ).fetchall()
        return {r["uid"] for r in rows}


def insert_message(
    mailbox_id: int,
    uid: int,
    folder: str,
    message_id: str | None,
    md5_hash: str,
    size: int,
    date: str | None,
    eml_path: str,
    sender: str = "",
    subject: str = "",
    content_type: str = "",
    snippet: str = "",
    is_large: bool = False,
    cloud_synced: int = 0,
    nas_synced: int = 0,
) -> int:
    with get_db() as conn:
        cur = conn.execute(
            """INSERT INTO messages
               (mailbox_id, uid, folder, message_id, md5_hash, size, date, eml_path,
                sender, subject, content_type, snippet, is_large, cloud_synced, nas_synced)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                mailbox_id, uid, folder, message_id, md5_hash, size, date, eml_path,
                sender, subject, content_type, snippet, int(is_large), cloud_synced, nas_synced,
            ),
        )
        return cur.lastrowid


def get_messages_by_message_id(mailbox_id: int, message_id: str) -> list[dict]:
    message_id = (message_id or "").strip()
    with get_db() as conn:
        rows = conn.execute(
            """SELECT * FROM messages
               WHERE mailbox_id = ? AND trim(message_id) = ?""",
            (mailbox_id, message_id),
        ).fetchall()
        return [dict(r) for r in rows]


def get_message(message_id: int) -> dict | None:
    with get_db() as conn:
        row = conn.execute("SELECT * FROM messages WHERE id = ?", (message_id,)).fetchone()
        return row_to_dict(row)


def list_restorable_messages(
    mailbox_id: int | None = None,
    domain_id: int | None = None,
    q: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> dict:
    """List backed-up messages available for selective restore to the server."""
    limit = max(1, min(int(limit or 100), 200))
    offset = max(0, int(offset or 0))
    query = (q or "").strip()
    like = f"%{query}%" if query else None

    with get_db() as conn:
        where = ["msg.eml_path IS NOT NULL", "trim(msg.eml_path) != ''"]
        params: list = []

        if mailbox_id:
            where.append("msg.mailbox_id = ?")
            params.append(mailbox_id)
        elif domain_id:
            where.append("m.domain_id = ?")
            params.append(domain_id)

        if like:
            where.append("(msg.subject LIKE ? OR msg.sender LIKE ? OR msg.message_id LIKE ?)")
            params.extend([like, like, like])

        where_sql = " AND ".join(where)
        count_row = conn.execute(
            f"""SELECT COUNT(*) as c FROM messages msg
                JOIN mailboxes m ON m.id = msg.mailbox_id
                WHERE {where_sql}""",
            params,
        ).fetchone()
        total = count_row["c"] if count_row else 0

        rows = conn.execute(
            f"""SELECT msg.id, msg.mailbox_id, msg.folder, msg.message_id, msg.size, msg.date,
                       msg.subject, msg.sender, msg.purge_status, m.email as mailbox_email
                FROM messages msg
                JOIN mailboxes m ON m.id = msg.mailbox_id
                WHERE {where_sql}
                ORDER BY msg.date DESC, msg.id DESC
                LIMIT ? OFFSET ?""",
            [*params, limit, offset],
        ).fetchall()

        return {
            "total": total,
            "limit": limit,
            "offset": offset,
            "items": [dict(r) for r in rows],
        }


def update_message_purge_status(message_id: int, status: str) -> None:
    with get_db() as conn:
        conn.execute(
            "UPDATE messages SET purge_status = ? WHERE id = ?",
            (status, message_id),
        )


def update_message_integrity(message_id: int, ok: bool) -> None:
    with get_db() as conn:
        conn.execute(
            "UPDATE messages SET integrity_ok = ?, verified_at = ? WHERE id = ?",
            (1 if ok else 0, now_iso(), message_id),
        )


def update_mailbox_integrity(mailbox_id: int, ok_count: int, total: int) -> None:
    with get_db() as conn:
        conn.execute(
            """UPDATE mailboxes
               SET last_integrity_at = ?, last_integrity_ok = ?, last_integrity_total = ?
               WHERE id = ?""",
            (now_iso(), ok_count, total, mailbox_id),
        )


def list_verified_purge_candidates(mailbox_id: int) -> list[dict]:
    """Messages that passed integrity audit and are not yet flagged/purged on the server."""
    with get_db() as conn:
        rows = conn.execute(
            """SELECT * FROM messages
               WHERE mailbox_id = ?
                 AND integrity_ok = 1
                 AND (purge_status IS NULL OR purge_status NOT IN ('flagged_deleted', 'purged'))
               ORDER BY folder, uid""",
            (mailbox_id,),
        ).fetchall()
        return [dict(r) for r in rows]


def get_mailbox_integrity_stats(mailbox_id: int) -> dict:
    with get_db() as conn:
        row = conn.execute(
            """SELECT
                 COUNT(*) as total,
                 SUM(CASE WHEN integrity_ok = 1 THEN 1 ELSE 0 END) as ok,
                 SUM(CASE WHEN integrity_ok = 0 THEN 1 ELSE 0 END) as failed,
                 SUM(CASE WHEN integrity_ok IS NULL THEN 1 ELSE 0 END) as unchecked
               FROM messages WHERE mailbox_id = ?""",
            (mailbox_id,),
        ).fetchone()
        mb = conn.execute(
            """SELECT last_integrity_at, last_integrity_ok, last_integrity_total
               FROM mailboxes WHERE id = ?""",
            (mailbox_id,),
        ).fetchone()
    stats = {
        "total": row["total"] or 0,
        "ok": row["ok"] or 0,
        "failed": row["failed"] or 0,
        "unchecked": row["unchecked"] or 0,
        "last_integrity_at": mb["last_integrity_at"] if mb else None,
        "last_integrity_ok": mb["last_integrity_ok"] if mb else None,
        "last_integrity_total": mb["last_integrity_total"] if mb else None,
    }
    stats["restore_ready"] = (
        stats["total"] > 0
        and stats["ok"] == stats["total"]
        and stats["unchecked"] == 0
    )
    return stats


def list_large_emails(mailbox_id: int | None = None, domain_id: int | None = None) -> list[dict]:
    with get_db() as conn:
        if mailbox_id:
            rows = conn.execute(
                """SELECT msg.*, m.email as mailbox_email FROM messages msg
                   JOIN mailboxes m ON m.id = msg.mailbox_id
                   WHERE msg.mailbox_id = ? AND msg.is_large = 1
                   ORDER BY msg.size DESC""",
                (mailbox_id,),
            ).fetchall()
        elif domain_id:
            rows = conn.execute(
                """SELECT msg.*, m.email as mailbox_email FROM messages msg
                   JOIN mailboxes m ON m.id = msg.mailbox_id
                   WHERE m.domain_id = ? AND msg.is_large = 1
                   ORDER BY msg.size DESC""",
                (domain_id,),
            ).fetchall()
        else:
            rows = conn.execute(
                """SELECT msg.*, m.email as mailbox_email FROM messages msg
                   JOIN mailboxes m ON m.id = msg.mailbox_id
                   WHERE msg.is_large = 1
                   ORDER BY msg.size DESC"""
            ).fetchall()
        return [dict(r) for r in rows]


def get_flagged_folders(mailbox_id: int) -> list[str]:
    with get_db() as conn:
        rows = conn.execute(
            """SELECT DISTINCT folder FROM messages
               WHERE mailbox_id = ? AND purge_status = 'flagged_deleted'""",
            (mailbox_id,),
        ).fetchall()
        return [r["folder"] for r in rows]


def mark_flagged_messages_purged(mailbox_id: int) -> None:
    with get_db() as conn:
        conn.execute(
            """UPDATE messages SET purge_status = 'purged'
               WHERE mailbox_id = ? AND purge_status = 'flagged_deleted'""",
            (mailbox_id,),
        )


def list_duplicates(mailbox_id: int | None = None, domain_id: int | None = None) -> list[dict]:
    with get_db() as conn:
        if mailbox_id:
            rows = conn.execute(
                """SELECT d.*, m.email as mailbox_email,
                          (SELECT msg.subject FROM messages msg
                           WHERE msg.mailbox_id = d.mailbox_id AND msg.message_id = d.message_id
                           AND msg.folder = 'INBOX' LIMIT 1) as subject,
                          (SELECT msg.date FROM messages msg
                           WHERE msg.mailbox_id = d.mailbox_id AND msg.message_id = d.message_id
                           AND msg.folder = 'INBOX' LIMIT 1) as date
                   FROM duplicates d
                   JOIN mailboxes m ON m.id = d.mailbox_id
                   WHERE d.mailbox_id = ? ORDER BY d.id DESC""",
                (mailbox_id,),
            ).fetchall()
        elif domain_id:
            rows = conn.execute(
                """SELECT d.*, m.email as mailbox_email,
                          (SELECT msg.subject FROM messages msg
                           WHERE msg.mailbox_id = d.mailbox_id AND msg.message_id = d.message_id
                           AND msg.folder = 'INBOX' LIMIT 1) as subject,
                          (SELECT msg.date FROM messages msg
                           WHERE msg.mailbox_id = d.mailbox_id AND msg.message_id = d.message_id
                           AND msg.folder = 'INBOX' LIMIT 1) as date
                   FROM duplicates d
                   JOIN mailboxes m ON m.id = d.mailbox_id
                   WHERE m.domain_id = ? ORDER BY d.id DESC""",
                (domain_id,),
            ).fetchall()
        else:
            rows = conn.execute(
                """SELECT d.*, m.email as mailbox_email,
                          (SELECT msg.subject FROM messages msg
                           WHERE msg.mailbox_id = d.mailbox_id AND msg.message_id = d.message_id
                           AND msg.folder = 'INBOX' LIMIT 1) as subject,
                          (SELECT msg.date FROM messages msg
                           WHERE msg.mailbox_id = d.mailbox_id AND msg.message_id = d.message_id
                           AND msg.folder = 'INBOX' LIMIT 1) as date
                   FROM duplicates d
                   JOIN mailboxes m ON m.id = d.mailbox_id ORDER BY d.id DESC"""
            ).fetchall()
        return [dict(r) for r in rows]


def insert_duplicate(
    mailbox_id: int, message_id: str, inbox_uid: int, sent_uid: int
) -> int | None:
    with get_db() as conn:
        try:
            cur = conn.execute(
                """INSERT INTO duplicates (mailbox_id, message_id, inbox_uid, sent_uid)
                   VALUES (?, ?, ?, ?)""",
                (mailbox_id, message_id, inbox_uid, sent_uid),
            )
            return cur.lastrowid
        except Exception:
            return None


def update_duplicate_status(duplicate_id: int, status: str) -> None:
    with get_db() as conn:
        conn.execute(
            "UPDATE duplicates SET status = ? WHERE id = ?",
            (status, duplicate_id),
        )


def get_duplicate(duplicate_id: int) -> dict | None:
    with get_db() as conn:
        row = conn.execute("SELECT * FROM duplicates WHERE id = ?", (duplicate_id,)).fetchone()
        return row_to_dict(row)


def clear_cleanup_suggestions(mailbox_id: int) -> None:
    with get_db() as conn:
        conn.execute(
            "DELETE FROM cleanup_suggestions WHERE mailbox_id = ? AND executed = 0",
            (mailbox_id,),
        )


def list_cleanup_suggestions(mailbox_id: int | None = None, domain_id: int | None = None) -> list[dict]:
    with get_db() as conn:
        if mailbox_id:
            rows = conn.execute(
                """SELECT cs.*, m.email as mailbox_email FROM cleanup_suggestions cs
                   JOIN mailboxes m ON m.id = cs.mailbox_id
                   WHERE cs.mailbox_id = ? ORDER BY cs.id DESC""",
                (mailbox_id,),
            ).fetchall()
        elif domain_id:
            rows = conn.execute(
                """SELECT cs.*, m.email as mailbox_email FROM cleanup_suggestions cs
                   JOIN mailboxes m ON m.id = cs.mailbox_id
                   WHERE m.domain_id = ? ORDER BY cs.id DESC""",
                (domain_id,),
            ).fetchall()
        else:
            rows = conn.execute(
                """SELECT cs.*, m.email as mailbox_email FROM cleanup_suggestions cs
                   JOIN mailboxes m ON m.id = cs.mailbox_id
                   ORDER BY cs.id DESC"""
            ).fetchall()
        result = []
        for r in rows:
            d = dict(r)
            d["message_ids"] = json.loads(d["message_ids"])
            _enrich_suggestion(conn, d)
            result.append(d)
        return result


def _enrich_suggestion(conn, suggestion: dict) -> None:
    labels = {
        "system_notifications": "System Notifications",
        "newsletter_clutter": "Newsletter Clutter",
        "bloated_threads": "Bloated Thread",
        "large_attachments": "Large Attachment",
    }
    suggestion["category_label"] = labels.get(
        suggestion.get("category", ""), suggestion.get("category", "").replace("_", " ").title()
    )
    if suggestion.get("executed"):
        suggestion["status"] = "flagged_deleted"
    elif suggestion.get("approved"):
        suggestion["status"] = "approved"
    else:
        suggestion["status"] = "pending"
    msg_ids = suggestion.get("message_ids") or []
    if suggestion.get("subject"):
        return
    if not msg_ids:
        return
    row = conn.execute(
        """SELECT msg.subject, msg.sender, msg.date, msg.folder, msg.size
           FROM messages msg
           WHERE msg.mailbox_id = ? AND msg.message_id = ?
           ORDER BY msg.date DESC LIMIT 1""",
        (suggestion["mailbox_id"], msg_ids[0]),
    ).fetchone()
    if not row:
        row = conn.execute(
            """SELECT msg.subject, msg.sender, msg.date, msg.folder, msg.size
               FROM messages msg
               WHERE msg.mailbox_id = ? AND msg.message_id LIKE ?
               ORDER BY msg.date DESC LIMIT 1""",
            (suggestion["mailbox_id"], f"%{msg_ids[0].strip('<>')}%"),
        ).fetchone()
    if row:
        suggestion.update(dict(row))


def insert_cleanup_suggestion(
    mailbox_id: int,
    category: str,
    message_ids: list[str],
    reason: str,
    subject: str = "",
    sender: str = "",
    date: str | None = None,
    folder: str = "",
    size: int = 0,
) -> int:
    with get_db() as conn:
        cur = conn.execute(
            """INSERT INTO cleanup_suggestions
               (mailbox_id, category, message_ids, reason, subject, sender, date, folder, size)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                mailbox_id, category, json.dumps(message_ids), reason,
                subject, sender, date, folder, size,
            ),
        )
        return cur.lastrowid


def get_cleanup_suggestion(suggestion_id: int) -> dict | None:
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM cleanup_suggestions WHERE id = ?", (suggestion_id,)
        ).fetchone()
        if not row:
            return None
        d = dict(row)
        d["message_ids"] = json.loads(d["message_ids"])
        return d


def mark_cleanup_approved(suggestion_ids: list[int]) -> None:
    with get_db() as conn:
        for sid in suggestion_ids:
            conn.execute(
                "UPDATE cleanup_suggestions SET approved = 1 WHERE id = ?",
                (sid,),
            )


def mark_cleanup_executed(suggestion_ids: list[int]) -> None:
    with get_db() as conn:
        for sid in suggestion_ids:
            conn.execute(
                "UPDATE cleanup_suggestions SET approved = 1, executed = 1 WHERE id = ?",
                (sid,),
            )


def create_backup_job(mailbox_id: int) -> int:
    with get_db() as conn:
        cur = conn.execute(
            "INSERT INTO backup_jobs (mailbox_id, status, started_at) VALUES (?, 'running', ?)",
            (mailbox_id, now_iso()),
        )
        return cur.lastrowid


def finish_backup_job(job_id: int, messages_added: int, error: str | None = None) -> None:
    status = "failed" if error else "completed"
    with get_db() as conn:
        conn.execute(
            """UPDATE backup_jobs SET status = ?, finished_at = ?, messages_added = ?, error = ?
               WHERE id = ?""",
            (status, now_iso(), messages_added, error, job_id),
        )


def update_mailbox_sync(mailbox_id: int) -> None:
    with get_db() as conn:
        conn.execute(
            "UPDATE mailboxes SET last_sync_at = ? WHERE id = ?",
            (now_iso(), mailbox_id),
        )


def mark_messages_cloud_synced(mailbox_id: int) -> None:
    with get_db() as conn:
        conn.execute(
            "UPDATE messages SET cloud_synced = 1 WHERE mailbox_id = ?",
            (mailbox_id,),
        )


def mark_messages_nas_synced(mailbox_id: int) -> None:
    with get_db() as conn:
        conn.execute(
            "UPDATE messages SET nas_synced = 1 WHERE mailbox_id = ?",
            (mailbox_id,),
        )


def get_stats(domain_id: int | None = None) -> dict:
    with get_db() as conn:
        domain_filter = "WHERE m.domain_id = ?" if domain_id else ""
        msg_filter = "WHERE m.mailbox_id IN (SELECT id FROM mailboxes m " + domain_filter + ")" if domain_id else ""
        dup_filter = "AND m.domain_id = ?" if domain_id else ""
        params = (domain_id,) if domain_id else ()

        domains = conn.execute("SELECT COUNT(*) as c FROM domains").fetchone()["c"]
        if domain_id:
            mailboxes = conn.execute(
                "SELECT COUNT(*) as c FROM mailboxes WHERE domain_id = ?", (domain_id,)
            ).fetchone()["c"]
            messages = conn.execute(
                """SELECT COUNT(*) as c FROM messages msg
                   JOIN mailboxes m ON m.id = msg.mailbox_id WHERE m.domain_id = ?""",
                (domain_id,),
            ).fetchone()["c"]
            total_size = conn.execute(
                """SELECT COALESCE(SUM(msg.size), 0) as s FROM messages msg
                   JOIN mailboxes m ON m.id = msg.mailbox_id WHERE m.domain_id = ?""",
                (domain_id,),
            ).fetchone()["s"]
            duplicates = conn.execute(
                """SELECT COUNT(*) as c FROM duplicates d
                   JOIN mailboxes m ON m.id = d.mailbox_id
                   WHERE d.status = 'flagged' AND m.domain_id = ?""",
                (domain_id,),
            ).fetchone()["c"]
            large = conn.execute(
                """SELECT COUNT(*) as c FROM messages msg
                   JOIN mailboxes m ON m.id = msg.mailbox_id
                   WHERE msg.is_large = 1 AND m.domain_id = ?""",
                (domain_id,),
            ).fetchone()["c"]
            last_jobs = conn.execute(
                """SELECT b.*, m.email FROM backup_jobs b
                   JOIN mailboxes m ON m.id = b.mailbox_id
                   WHERE m.domain_id = ? ORDER BY b.id DESC LIMIT 10""",
                (domain_id,),
            ).fetchall()
            mailbox_stats = conn.execute(
                """SELECT m.id, m.email, d.name as domain_name, m.last_sync_at,
                          COUNT(msg.id) as message_count,
                          COALESCE(SUM(msg.size), 0) as total_size,
                          SUM(CASE WHEN msg.is_large = 1 THEN 1 ELSE 0 END) as large_count
                   FROM mailboxes m
                   JOIN domains d ON d.id = m.domain_id
                   LEFT JOIN messages msg ON msg.mailbox_id = m.id
                   WHERE m.domain_id = ?
                   GROUP BY m.id ORDER BY m.email""",
                (domain_id,),
            ).fetchall()
        else:
            mailboxes = conn.execute("SELECT COUNT(*) as c FROM mailboxes").fetchone()["c"]
            messages = conn.execute("SELECT COUNT(*) as c FROM messages").fetchone()["c"]
            total_size = conn.execute("SELECT COALESCE(SUM(size), 0) as s FROM messages").fetchone()["s"]
            duplicates = conn.execute(
                "SELECT COUNT(*) as c FROM duplicates WHERE status = 'flagged'"
            ).fetchone()["c"]
            large = conn.execute("SELECT COUNT(*) as c FROM messages WHERE is_large = 1").fetchone()["c"]
            last_jobs = conn.execute(
                """SELECT b.*, m.email FROM backup_jobs b
                   JOIN mailboxes m ON m.id = b.mailbox_id
                   ORDER BY b.id DESC LIMIT 10"""
            ).fetchall()
            mailbox_stats = conn.execute(
                """SELECT m.id, m.email, d.name as domain_name, m.last_sync_at,
                          COUNT(msg.id) as message_count,
                          COALESCE(SUM(msg.size), 0) as total_size,
                          SUM(CASE WHEN msg.is_large = 1 THEN 1 ELSE 0 END) as large_count
                   FROM mailboxes m
                   JOIN domains d ON d.id = m.domain_id
                   LEFT JOIN messages msg ON msg.mailbox_id = m.id
                   GROUP BY m.id ORDER BY m.email"""
            ).fetchall()
        return {
            "domains": domains,
            "mailboxes": mailboxes,
            "messages": messages,
            "total_size": total_size,
            "duplicates": duplicates,
            "large_emails": large,
            "last_jobs": [dict(r) for r in last_jobs],
            "mailbox_stats": [dict(r) for r in mailbox_stats],
        }


def ensure_admin(username: str, password_hash: str) -> None:
    with get_db() as conn:
        row = conn.execute(
            "SELECT id FROM admin_users WHERE username = ?", (username,)
        ).fetchone()
        if not row:
            conn.execute(
                "INSERT INTO admin_users (username, password_hash) VALUES (?, ?)",
                (username, password_hash),
            )


def get_admin(username: str) -> dict | None:
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM admin_users WHERE username = ?", (username,)
        ).fetchone()
        return row_to_dict(row)
