import os
import json
import tempfile
from pathlib import Path
from datetime import datetime
import pytest

import database
from security import (
    GENESIS_HASH,
    append_audit_log_file,
    verify_audit_log_chain,
    check_append_only_attribute,
    enable_append_only_attribute,
    secure_session_directories,
    ensure_gitignore_entries,
)


def test_audit_log_hash_chain_and_format():
    """Verify that outgoing messages form a valid SHA-256 hash chain in JSON Lines format."""
    with tempfile.NamedTemporaryFile(suffix=".log", delete=False) as tmp:
        tmp_log_path = tmp.name

    try:
        test_jid = "905551234567@c.us"
        test_msg_1 = "Merhaba Masal Kamp'a hoş geldiniz! 🏕️"
        test_msg_2 = "Giriş saatimiz 13:00, çıkış 11:00'dir."
        test_msg_3 = "Fiyat bilgisi: Çadır yeri 800 TL'dir."

        entry1 = append_audit_log_file(test_jid, test_msg_1, status="SENT", log_file_path=tmp_log_path)
        entry2 = append_audit_log_file(test_jid, test_msg_2, status="SENT", log_file_path=tmp_log_path)
        entry3 = append_audit_log_file(test_jid, test_msg_3, status="FAILED", log_file_path=tmp_log_path)

        assert entry1 is not None
        assert entry2 is not None
        assert entry3 is not None

        # Verify Genesis link
        assert entry1["prev_hash"] == GENESIS_HASH
        assert len(entry1["entry_hash"]) == 64

        # Verify Chain continuity
        assert entry2["prev_hash"] == entry1["entry_hash"]
        assert entry3["prev_hash"] == entry2["entry_hash"]

        # Run cryptographic verification
        report = verify_audit_log_chain(log_file_path=tmp_log_path)
        assert report["is_valid"] is True
        assert report["total_records"] == 3
        assert report["latest_hash"] == entry3["entry_hash"]
        assert report["failed_at_line"] is None
        assert report["error"] is None
    finally:
        if os.path.exists(tmp_log_path):
            os.remove(tmp_log_path)


def test_tamper_detection_modified_content():
    """Verify that modifying message content in the middle of the log breaks the hash chain."""
    with tempfile.NamedTemporaryFile(suffix=".log", delete=False) as tmp:
        tmp_log_path = tmp.name

    try:
        append_audit_log_file("905551112233", "Mesaj 1 - Orijinal", status="SENT", log_file_path=tmp_log_path)
        append_audit_log_file("905551112233", "Mesaj 2 - Orijinal", status="SENT", log_file_path=tmp_log_path)
        append_audit_log_file("905551112233", "Mesaj 3 - Orijinal", status="SENT", log_file_path=tmp_log_path)

        # Confirm clean chain
        clean_report = verify_audit_log_chain(log_file_path=tmp_log_path)
        assert clean_report["is_valid"] is True

        # Now tamper with line 2 message content without recomputing hash
        with open(tmp_log_path, "r", encoding="utf-8") as f:
            lines = [json.loads(l) for l in f if l.strip()]

        lines[1]["message_preview"] = "Mesaj 2 - Değiştirilmiş / Sahte İçerik!"

        with open(tmp_log_path, "w", encoding="utf-8") as f:
            for item in lines:
                f.write(json.dumps(item) + "\n")

        # Verify that tamper is caught immediately
        tampered_report = verify_audit_log_chain(log_file_path=tmp_log_path)
        assert tampered_report["is_valid"] is False
        assert tampered_report["failed_at_line"] == 2
        assert "Tampering detected" in tampered_report["error"]
    finally:
        if os.path.exists(tmp_log_path):
            os.remove(tmp_log_path)


def test_tamper_detection_deleted_line():
    """Verify that deleting a record from the middle breaks the previous hash linkage."""
    with tempfile.NamedTemporaryFile(suffix=".log", delete=False) as tmp:
        tmp_log_path = tmp.name

    try:
        append_audit_log_file("905551112233", "Adım 1", status="SENT", log_file_path=tmp_log_path)
        append_audit_log_file("905551112233", "Adım 2 (Silinecek)", status="SENT", log_file_path=tmp_log_path)
        append_audit_log_file("905551112233", "Adım 3", status="SENT", log_file_path=tmp_log_path)

        # Read and delete second line
        with open(tmp_log_path, "r", encoding="utf-8") as f:
            lines = [l for l in f if l.strip()]

        del lines[1]  # Delete middle line

        with open(tmp_log_path, "w", encoding="utf-8") as f:
            f.writelines(lines)

        # Verify that chain discontinuity is caught
        tampered_report = verify_audit_log_chain(log_file_path=tmp_log_path)
        assert tampered_report["is_valid"] is False
        assert tampered_report["failed_at_line"] == 2
        assert "Chain broken" in tampered_report["error"]
    finally:
        if os.path.exists(tmp_log_path):
            os.remove(tmp_log_path)


def test_sqlite_audit_log_hash_chain():
    """Verify that outgoing messages in the SQLite bot_audit_logs table form a valid hash chain."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        tmp_db_path = tmp.name

    try:
        database.init_db(tmp_db_path)
        e1 = database.log_bot_audit("905559876543", "Talebinizi aldım, yetkilimiz dönüş yapacaktır.", status="SENT", db_path=tmp_db_path)
        e2 = database.log_bot_audit("905559876543", "Fiyat teklifimiz iletildi.", status="SENT", db_path=tmp_db_path)
        e3 = database.log_bot_audit("905559876543", "İyi günler dileriz.", status="SENT", db_path=tmp_db_path)

        assert e1["prev_hash"] == GENESIS_HASH
        assert e2["prev_hash"] == e1["entry_hash"]
        assert e3["prev_hash"] == e2["entry_hash"]

        # Verification function
        db_report = database.verify_db_audit_chain(db_path=tmp_db_path)
        assert db_report["is_valid"] is True
        assert db_report["total_records"] == 3
        assert db_report["latest_hash"] == e3["entry_hash"]

        # Check tamper detection in SQLite
        with database.get_db(tmp_db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE bot_audit_logs SET message_preview = 'Hileli Mesaj' WHERE id = 2;")

        tampered_db_report = database.verify_db_audit_chain(db_path=tmp_db_path)
        assert tampered_db_report["is_valid"] is False
        assert tampered_db_report["failed_at_id"] == 2
    finally:
        if os.path.exists(tmp_db_path):
            os.remove(tmp_db_path)


def test_gitignore_auto_sync():
    """Verify that ensure_gitignore_entries automatically appends required security patterns."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_gitignore = Path(tmp_dir) / ".gitignore"
        tmp_gitignore.write_text("node_modules/\n*.pyc\n", encoding="utf-8")

        ensure_gitignore_entries(repo_root=tmp_dir)

        content = tmp_gitignore.read_text(encoding="utf-8")
        assert ".env" in content
        assert "bot_audit.log" in content
        assert ".wwebjs_auth/" in content
        assert "auth_info/" in content
        assert "session/" in content
