"""Message-ID cross-folder duplicate detection."""

import logging

from db import models
from db.database import get_db

logger = logging.getLogger(__name__)

INBOX_ALIASES = {"INBOX", "Inbox", "inbox"}
SENT_ALIASES = {
    "Sent", "SENT", "Sent Items", "Sent Messages",
    "INBOX.Sent", "INBOX/Sent", "[Gmail]/Sent Mail", "Sent Mail",
}


def _normalize_folder(folder: str) -> str:
    if folder in INBOX_ALIASES:
        return "INBOX"
    if folder in SENT_ALIASES:
        return "Sent"
    return folder


def _normalize_message_id(message_id: str | None) -> str:
    return (message_id or "").strip()


def _flag_pair(
    mailbox_id: int,
    message_id: str,
    inbox_uid: int,
    sent_uid: int,
    log_fn=None,
) -> int | None:
    dup_id = models.insert_duplicate(mailbox_id, message_id, inbox_uid, sent_uid)
    if dup_id:
        logger.info(
            "Duplicate flagged: mailbox=%s message_id=%s inbox_uid=%s sent_uid=%s",
            mailbox_id, message_id, inbox_uid, sent_uid,
        )
        if log_fn:
            log_fn(f"Duplicate flagged: inbox_uid={inbox_uid} (same email in Inbox and Sent)")
    return dup_id


def find_inbox_sent_pairs(mailbox_id: int) -> list[dict]:
    """Return inbox/sent pairs that qualify as duplicates (Message-ID or identical MD5)."""
    pairs: list[dict] = []
    seen_keys: set[str] = set()

    with get_db() as conn:
        for row in conn.execute(
            """SELECT trim(a.message_id) AS message_id, a.uid AS inbox_uid, b.uid AS sent_uid
               FROM messages a
               JOIN messages b ON a.mailbox_id = b.mailbox_id
                 AND trim(a.message_id) = trim(b.message_id)
                 AND a.message_id IS NOT NULL AND trim(a.message_id) != ''
               WHERE a.mailbox_id = ? AND a.folder = 'INBOX' AND b.folder = 'Sent'""",
            (mailbox_id,),
        ).fetchall():
            key = f"mid:{row['message_id']}"
            if key in seen_keys:
                continue
            seen_keys.add(key)
            pairs.append(
                {
                    "message_id": row["message_id"],
                    "inbox_uid": row["inbox_uid"],
                    "sent_uid": row["sent_uid"],
                }
            )

        for row in conn.execute(
            """SELECT a.message_id AS inbox_mid, a.uid AS inbox_uid, b.uid AS sent_uid, a.md5_hash
               FROM messages a
               JOIN messages b ON a.mailbox_id = b.mailbox_id
                 AND a.md5_hash = b.md5_hash
                 AND a.md5_hash IS NOT NULL AND a.md5_hash != ''
                 AND trim(coalesce(a.message_id, '')) != trim(coalesce(b.message_id, ''))
               WHERE a.mailbox_id = ? AND a.folder = 'INBOX' AND b.folder = 'Sent'""",
            (mailbox_id,),
        ).fetchall():
            message_id = _normalize_message_id(row["inbox_mid"]) or f"md5:{row['md5_hash']}"
            key = f"md5:{row['md5_hash']}:{row['inbox_uid']}:{row['sent_uid']}"
            if key in seen_keys:
                continue
            seen_keys.add(key)
            pairs.append(
                {
                    "message_id": message_id,
                    "inbox_uid": row["inbox_uid"],
                    "sent_uid": row["sent_uid"],
                }
            )

    return pairs


def check_and_flag_duplicate(mailbox_id: int, message_id: str) -> int | None:
    """If same Message-ID exists in INBOX and Sent, flag as duplicate."""
    message_id = _normalize_message_id(message_id)
    if not message_id:
        return None

    matches = models.get_messages_by_message_id(mailbox_id, message_id)
    if len(matches) < 2:
        return None

    folders = {_normalize_folder(m["folder"]) for m in matches}
    if "INBOX" not in folders or "Sent" not in folders:
        return None

    inbox_uid = next(
        (m["uid"] for m in matches if _normalize_folder(m["folder"]) == "INBOX"), None
    )
    sent_uid = next(
        (m["uid"] for m in matches if _normalize_folder(m["folder"]) == "Sent"), None
    )
    if inbox_uid is None or sent_uid is None:
        return None

    return _flag_pair(mailbox_id, message_id, inbox_uid, sent_uid)


def rescan_mailbox_duplicates(mailbox_id: int, log_fn=None) -> int:
    """Scan all backed-up messages and flag any missing inbox/sent duplicate pairs."""
    added = 0
    for pair in find_inbox_sent_pairs(mailbox_id):
        if _flag_pair(
            mailbox_id,
            pair["message_id"],
            pair["inbox_uid"],
            pair["sent_uid"],
            log_fn=log_fn,
        ):
            added += 1
    return added
