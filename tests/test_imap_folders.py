"""IMAP folder discovery tests."""

from imap.folders import _parse_list_line, discover_folders, list_mailbox_folders


class FakeConn:
    def __init__(self, lines):
        self._lines = lines

    def list(self):
        return "OK", self._lines


def test_parse_list_line():
    name, flags = _parse_list_line(b'(\\HasNoChildren) "/" "INBOX.Sent"')
    assert name == "INBOX.Sent"
    assert "\\HasNoChildren" in flags


def test_parse_list_line_unquoted():
    name, flags = _parse_list_line(b'(\\HasNoChildren) "." INBOX.Trash')
    assert name == "INBOX.Trash"


def test_discover_inbox_sent_hostinger_style():
    lines = [
        b'(\\HasNoChildren) "/" "INBOX"',
        b'(\\HasNoChildren \\Sent) "/" "INBOX.Sent"',
        b'(\\HasNoChildren \\Trash) "/" "INBOX.Trash"',
    ]
    result = discover_folders(FakeConn(lines))
    assert result["INBOX"] == "INBOX"
    assert result["Sent"] == "INBOX.Sent"


def test_discover_sent_by_name():
    lines = [
        b'(\\HasNoChildren) "/" "INBOX"',
        b'(\\HasNoChildren) "/" "Sent Items"',
    ]
    result = discover_folders(FakeConn(lines))
    assert result["Sent"] == "Sent Items"


def test_list_all_selectable_folders():
    lines = [
        b'(\\Noselect \\HasChildren) "/" "INBOX"',
        b'(\\HasNoChildren) "/" "INBOX"',
        b'(\\HasNoChildren \\Sent) "/" "INBOX.Sent"',
        b'(\\HasNoChildren \\Trash) "/" "INBOX.Trash"',
        b'(\\HasNoChildren) "/" "Archive"',
    ]
    result = list_mailbox_folders(FakeConn(lines))
    assert result == ["INBOX", "Archive", "INBOX.Sent", "INBOX.Trash"]


def test_canonical_folder_name():
    from imap.folders import canonical_folder_name

    assert canonical_folder_name("INBOX") == "INBOX"
    assert canonical_folder_name("INBOX.Sent") == "Sent"
    assert canonical_folder_name("INBOX.Trash") == "INBOX.Trash"
    assert canonical_folder_name("Archive") == "Archive"


def test_list_skips_nonexistent():
    lines = [
        b'(\\HasNoChildren) "/" "INBOX"',
        b'(\\Nonexistent) "/" "Ghost"',
    ]
    result = list_mailbox_folders(FakeConn(lines))
    assert result == ["INBOX"]
