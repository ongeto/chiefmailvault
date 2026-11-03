"""Discover IMAP folder names on the server."""

import logging
import re

logger = logging.getLogger(__name__)

# Known aliases for dedup normalization (server name -> logical)
SENT_NAMES = (
    "Sent",
    "SENT",
    "Sent Items",
    "Sent Messages",
    "INBOX.Sent",
    "INBOX/Sent",
    "[Gmail]/Sent Mail",
    "Sent Mail",
)

INBOX_NAMES = ("INBOX", "Inbox", "inbox")

SKIP_FLAGS = {r"\Noselect", r"\Nonexistent"}


def _parse_list_line(line: bytes | str) -> tuple[str, list[str]] | None:
    """Parse LIST response into (folder_name, flags)."""
    if isinstance(line, bytes):
        line = line.decode("utf-8", errors="replace")

    flag_end = line.find(")")
    if flag_end == -1:
        return None

    flags = [f.strip() for f in line[1:flag_end].split() if f.strip()]
    rest = line[flag_end + 1 :].strip()
    if not rest:
        return None

    # Delimiter is second token; mailbox name is the remainder.
    parts = rest.split(" ", 1)
    if len(parts) < 2:
        return None

    raw_name = parts[1].strip().strip('"')
    if not raw_name:
        return None
    return raw_name, flags


def _list_all(conn) -> list[tuple[str, list[str]]]:
    status, data = conn.list()
    if status != "OK" or not data:
        return []

    folders: list[tuple[str, list[str]]] = []
    for line in data:
        if not line:
            continue
        parsed = _parse_list_line(line)
        if parsed:
            folders.append(parsed)
    return folders


def list_mailbox_folders(conn) -> list[str]:
    """
    Return all selectable IMAP folders on the server, INBOX first.
  """
    folders = _list_all(conn)
    selectable = [(name, flags) for name, flags in folders if not SKIP_FLAGS.intersection(flags)]

    def sort_key(item: tuple[str, list[str]]) -> tuple[int, str]:
        name, flags = item
        if r"\Inbox" in flags or name.upper() == "INBOX":
            return (0, name.lower())
        return (1, name.lower())

    names = [name for name, _ in sorted(selectable, key=sort_key)]
    logger.info("Discovered %d selectable folder(s): %s", len(names), names)
    return names


def discover_folders(conn) -> dict[str, str]:
    """
    Map logical folders to actual server names (used by dedup helpers).
    Returns e.g. {'INBOX': 'INBOX', 'Sent': 'INBOX.Sent'}
    """
    folders = _list_all(conn)
    if not folders:
        return {"INBOX": "INBOX", "Sent": "Sent"}

    resolved: dict[str, str] = {}
    folder_names = {name for name, _ in folders}

    for name, flags in folders:
        if r"\Inbox" in flags or name.upper() == "INBOX":
            resolved["INBOX"] = name
            break
    if "INBOX" not in resolved:
        for candidate in INBOX_NAMES:
            if candidate in folder_names:
                resolved["INBOX"] = candidate
                break
    if "INBOX" not in resolved:
        resolved["INBOX"] = "INBOX"

    for name, flags in folders:
        if r"\Sent" in flags:
            resolved["Sent"] = name
            break
    if "Sent" not in resolved:
        for candidate in SENT_NAMES:
            if candidate in folder_names:
                resolved["Sent"] = candidate
                break
    if "Sent" not in resolved:
        lower_map = {n.lower(): n for n in folder_names}
        for candidate in SENT_NAMES:
            if candidate.lower() in lower_map:
                resolved["Sent"] = lower_map[candidate.lower()]
                break

    return resolved


def canonical_folder_name(imap_folder: str) -> str:
    """Map server folder names to stable storage keys (INBOX/Sent aliases preserved)."""
    if imap_folder.upper() == "INBOX" or imap_folder in INBOX_NAMES:
        return "INBOX"
    if imap_folder in SENT_NAMES:
        return "Sent"
    lower_sent = {name.lower() for name in SENT_NAMES}
    if imap_folder.lower() in lower_sent:
        return "Sent"
    return imap_folder


def resolve_imap_folder_name(conn, folder_key: str) -> str:
    """Map stored folder key back to the server's IMAP folder name."""
    mapping = discover_folders(conn)
    if folder_key == "INBOX":
        return mapping.get("INBOX", folder_key)
    if folder_key == "Sent":
        return mapping.get("Sent", folder_key)
    return folder_key
