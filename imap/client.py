"""IMAP connection wrapper with rate limiting, keepalive, and auto-reconnect."""

import imaplib
import logging
import socket
import time
from typing import Callable, TypeVar

from config import (
    IMAP_FETCH_TIMEOUT_SECONDS,
    IMAP_KEEPALIVE_EVERY_N_OPS,
    IMAP_KEEPALIVE_INTERVAL_SECONDS,
    IMAP_MAX_RETRIES,
    IMAP_RETRY_DELAY_SECONDS,
    IMAP_THROTTLE_SECONDS,
    IMAP_TIMEOUT_SECONDS,
)

logger = logging.getLogger(__name__)

T = TypeVar("T")

CONNECTION_ERRORS = (
    ConnectionResetError,
    ConnectionAbortedError,
    BrokenPipeError,
    TimeoutError,
    socket.timeout,
    OSError,
    imaplib.IMAP4.abort,
)


class ImapClient:
    """SSL IMAP client with throttled operations, keepalive, and reconnect."""

    def __init__(self, host: str, port: int, email: str, password: str) -> None:
        self.host = host
        self.port = port
        self.email = email
        self.password = password
        self._conn: imaplib.IMAP4_SSL | None = None
        self._selected_folder: str | None = None
        self._last_keepalive = time.monotonic()
        self._ops_since_keepalive = 0

    def connect(self) -> None:
        self._conn = imaplib.IMAP4_SSL(self.host, self.port, timeout=IMAP_TIMEOUT_SECONDS)
        self._conn.login(self.email, self.password)
        self._last_keepalive = time.monotonic()
        self._ops_since_keepalive = 0
        logger.info("IMAP connected: %s@%s", self.email, self.host)

    def disconnect(self, clear_folder: bool = True) -> None:
        if self._conn:
            try:
                self._conn.logout()
            except Exception:
                pass
            self._conn = None
        if clear_folder:
            self._selected_folder = None

    def reconnect(self, log_fn=None) -> None:
        """Drop and re-establish the IMAP session, re-selecting the active folder."""
        _log = log_fn or logger.info
        folder = self._selected_folder
        _log(f"IMAP reconnecting {self.email}...")
        self.disconnect(clear_folder=False)
        time.sleep(IMAP_RETRY_DELAY_SECONDS)
        self.connect()
        if folder:
            self._select_folder_direct(folder)
            _log(f"IMAP reconnected {self.email} (folder: {folder})")
        else:
            _log(f"IMAP reconnected {self.email}")

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, *args):
        self.disconnect()

    @property
    def conn(self) -> imaplib.IMAP4_SSL:
        if not self._conn:
            raise RuntimeError("IMAP not connected")
        return self._conn

    def throttle(self) -> None:
        time.sleep(IMAP_THROTTLE_SECONDS)

    def _select_folder_direct(self, folder: str) -> None:
        """SELECT a folder without the retry wrapper (used during reconnect)."""
        candidates = [folder]
        if " " in folder or "." in folder or "/" in folder or "[" in folder:
            candidates.insert(0, f'"{folder}"')
        else:
            candidates.append(f'"{folder}"')

        last_status = None
        for name in dict.fromkeys(candidates):
            status, _ = self.conn.select(name)
            last_status = status
            if status == "OK":
                self._selected_folder = folder
                return
        raise RuntimeError(f"Failed to select folder: {folder} (status={last_status})")

    def _ensure_selected(self) -> None:
        """Re-select the active folder if the session is not in SELECTED state."""
        if not self._selected_folder:
            return
        state = getattr(self.conn, "state", None)
        if state != "SELECTED":
            self._select_folder_direct(self._selected_folder)

    def _keepalive(self) -> None:
        self._ensure_selected()
        self.conn.noop()
        self._last_keepalive = time.monotonic()
        self._ops_since_keepalive = 0

    def _maybe_keepalive(self) -> None:
        self._ops_since_keepalive += 1
        elapsed = time.monotonic() - self._last_keepalive
        if (
            elapsed >= IMAP_KEEPALIVE_INTERVAL_SECONDS
            or self._ops_since_keepalive >= IMAP_KEEPALIVE_EVERY_N_OPS
        ):
            self._keepalive()

    def _recover_from_protocol_error(self, exc: imaplib.IMAP4.error) -> bool:
        """Re-select folder after AUTH-state errors; return True if recovered."""
        msg = str(exc).lower()
        if self._selected_folder and "illegal in state" in msg:
            self._select_folder_direct(self._selected_folder)
            return True
        return False

    def _with_retry(self, operation: str, fn: Callable[[], T], log_fn=None) -> T:
        _log = log_fn or (lambda msg: None)
        last_exc: Exception | None = None
        for attempt in range(1, IMAP_MAX_RETRIES + 1):
            try:
                self._maybe_keepalive()
                return fn()
            except imaplib.IMAP4.error as exc:
                if self._recover_from_protocol_error(exc) and attempt < IMAP_MAX_RETRIES:
                    logger.warning(
                        "IMAP %s protocol error for %s — re-selected folder (attempt %d/%d): %s",
                        operation, self.email, attempt, IMAP_MAX_RETRIES, exc,
                    )
                    last_exc = exc
                    continue
                raise
            except CONNECTION_ERRORS as exc:
                last_exc = exc
                logger.warning(
                    "IMAP %s failed for %s (attempt %d/%d): %s",
                    operation, self.email, attempt, IMAP_MAX_RETRIES, exc,
                )
                if attempt >= IMAP_MAX_RETRIES:
                    break
                _log(f"IMAP connection lost during {operation} — reconnecting ({attempt}/{IMAP_MAX_RETRIES})...")
                self.reconnect(log_fn=_log)
        raise last_exc  # type: ignore[misc]

    def list_folders(self, log_fn=None) -> list[str]:
        from imap.folders import list_mailbox_folders

        def _list() -> list[str]:
            self.throttle()
            return list_mailbox_folders(self.conn)

        return self._with_retry("LIST", _list, log_fn=log_fn)

    def select_folder(self, folder: str, throttle: bool = True) -> None:
        def _select() -> None:
            if throttle:
                self.throttle()
            self._select_folder_direct(folder)

        self._with_retry(f"SELECT {folder}", _select)

    def search_all_uids(self, log_fn=None) -> list[int]:
        def _search() -> list[int]:
            self._ensure_selected()
            self.throttle()
            status, data = self.conn.uid("SEARCH", None, "ALL")
            if status != "OK" or not data[0]:
                return []
            return [int(u) for u in data[0].split()]

        return self._with_retry("SEARCH", _search, log_fn=log_fn)

    def fetch_rfc822(self, uid: int, log_fn=None) -> bytes | None:
        def _fetch() -> bytes | None:
            self._ensure_selected()
            self.throttle()
            if IMAP_FETCH_TIMEOUT_SECONDS != IMAP_TIMEOUT_SECONDS and self._conn:
                self._conn.sock.settimeout(IMAP_FETCH_TIMEOUT_SECONDS)  # type: ignore[attr-defined]
            try:
                status, data = self.conn.uid("FETCH", str(uid), "(RFC822)")
            finally:
                if self._conn:
                    self._conn.sock.settimeout(IMAP_TIMEOUT_SECONDS)  # type: ignore[attr-defined]
            if status != "OK" or not data or data[0] is None:
                return None
            return data[0][1]

        return self._with_retry(f"FETCH uid={uid}", _fetch, log_fn=log_fn)

    def flag_deleted(self, uid: int, folder: str = "INBOX", log_fn=None) -> None:
        def _flag() -> None:
            self._select_folder_direct(folder)
            self.throttle()
            self.conn.uid("STORE", str(uid), "+FLAGS", "\\Deleted")

        self._with_retry(f"STORE uid={uid}", _flag, log_fn=log_fn)

    def expunge(self, log_fn=None) -> None:
        def _expunge() -> None:
            self._ensure_selected()
            self.throttle()
            self.conn.expunge()

        self._with_retry("EXPUNGE", _expunge, log_fn=log_fn)

    def message_id_exists(self, message_id: str, folder: str, log_fn=None) -> bool:
        """Return True if a message with this Message-ID already exists in the folder."""
        mid = (message_id or "").strip()
        if not mid:
            return False

        def _search() -> bool:
            self._select_folder_direct(folder)
            self.throttle()
            # HEADER Message-ID values are often angle-bracketed; try both forms.
            candidates = [mid]
            if mid.startswith("<") and mid.endswith(">"):
                candidates.append(mid[1:-1])
            else:
                candidates.append(f"<{mid}>")
            for value in dict.fromkeys(candidates):
                status, data = self.conn.uid("SEARCH", None, "HEADER", "Message-ID", value)
                if status == "OK" and data and data[0]:
                    return True
            return False

        return self._with_retry(f"SEARCH Message-ID folder={folder}", _search, log_fn=log_fn)

    def append(
        self,
        folder: str,
        raw: bytes,
        flags: str = "\\Seen",
        date_time=None,
        log_fn=None,
    ) -> None:
        """Upload a raw RFC822 message into a mailbox folder via IMAP APPEND."""
        if not raw:
            raise ValueError("Cannot APPEND empty message")

        def _append() -> None:
            self.throttle()
            # APPEND does not require SELECTED state, but keep folder tracking honest.
            status, _ = self.conn.append(folder, flags, date_time, raw)
            if status != "OK":
                # Retry with quoted folder name for Hostinger-style INBOX.Sent paths.
                quoted = folder if folder.startswith('"') else f'"{folder}"'
                status2, _ = self.conn.append(quoted, flags, date_time, raw)
                if status2 != "OK":
                    raise RuntimeError(f"APPEND failed for folder={folder} (status={status2})")

        self._with_retry(f"APPEND folder={folder}", _append, log_fn=log_fn)
