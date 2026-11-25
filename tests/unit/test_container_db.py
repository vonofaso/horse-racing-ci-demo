"""Reject accidental destructive operations before calling Docker."""

from unittest.mock import Mock

import pytest

from scripts import container_db


def test_restore_requires_confirmation_before_docker(monkeypatch, tmp_path):
    archive = tmp_path / "backup.dump"
    archive.write_bytes(b"archive")
    monkeypatch.delenv("CONFIRM_RESTORE", raising=False)
    run = Mock()
    monkeypatch.setattr(container_db, "run", run)
    with pytest.raises(ValueError, match="CONFIRM_RESTORE"):
        container_db.restore([], archive)
    run.assert_not_called()


def test_restore_requires_existing_file_before_docker(monkeypatch, tmp_path):
    monkeypatch.setenv("CONFIRM_RESTORE", "YES")
    run = Mock()
    monkeypatch.setattr(container_db, "run", run)
    with pytest.raises(FileNotFoundError):
        container_db.restore([], tmp_path / "missing.dump")
    run.assert_not_called()


def test_backup_does_not_replace_existing_archive(monkeypatch, tmp_path):
    archive = tmp_path / "backup.dump"
    archive.write_bytes(b"original")
    run = Mock()
    monkeypatch.setattr(container_db, "run", run)
    with pytest.raises(FileExistsError):
        container_db.backup([], archive)
    assert archive.read_bytes() == b"original"
    run.assert_not_called()
