"""IMAP client reconnect tests."""

import imaplib
from unittest.mock import MagicMock, patch

import pytest

from imap.client import CONNECTION_ERRORS, ImapClient


def test_with_retry_reconnects_on_connection_reset():
    client = ImapClient("imap.test.com", 993, "user@test.com", "pass")
    client._conn = MagicMock()
    client._selected_folder = "INBOX"

    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        if calls["n"] == 1:
            raise ConnectionResetError(10054, "forcibly closed")
        return "ok"

    with patch.object(client, "reconnect") as mock_reconnect, patch.object(client, "_maybe_keepalive"):
        result = client._with_retry("TEST", flaky)
        assert result == "ok"
        mock_reconnect.assert_called_once()


def test_with_retry_raises_after_max_attempts():
    client = ImapClient("imap.test.com", 993, "user@test.com", "pass")
    client._conn = MagicMock()

    with patch.object(client, "reconnect"), patch.object(client, "_maybe_keepalive"), patch(
        "imap.client.IMAP_MAX_RETRIES", 2
    ):
        with pytest.raises(ConnectionResetError):
            client._with_retry("TEST", lambda: (_ for _ in ()).throw(ConnectionResetError(10054, "closed")))


def test_reconnect_preserves_and_reselects_folder():
    client = ImapClient("imap.test.com", 993, "user@test.com", "pass")
    client._selected_folder = "INBOX.Sent"
    client._conn = MagicMock()
    client._conn.state = "SELECTED"

    with patch.object(client, "disconnect") as mock_disconnect, patch.object(
        client, "connect"
    ), patch.object(client, "_select_folder_direct") as mock_select:
        client.reconnect()
        mock_disconnect.assert_called_once_with(clear_folder=False)
        mock_select.assert_called_once_with("INBOX.Sent")


def test_ensure_selected_reselects_when_in_auth_state():
    client = ImapClient("imap.test.com", 993, "user@test.com", "pass")
    client._conn = MagicMock()
    client._conn.state = "AUTH"
    client._selected_folder = "Sent"

    with patch.object(client, "_select_folder_direct") as mock_select:
        client._ensure_selected()
        mock_select.assert_called_once_with("Sent")


def test_recover_from_protocol_error():
    client = ImapClient("imap.test.com", 993, "user@test.com", "pass")
    client._selected_folder = "INBOX"
    client._conn = MagicMock()

    with patch.object(client, "_select_folder_direct") as mock_select:
        recovered = client._recover_from_protocol_error(
            imaplib.IMAP4.error("command FETCH illegal in state AUTH, only allowed in states SELECTED")
        )
        assert recovered is True
        mock_select.assert_called_once_with("INBOX")


def test_connection_errors_include_socket_timeout():
    assert ConnectionResetError in CONNECTION_ERRORS
