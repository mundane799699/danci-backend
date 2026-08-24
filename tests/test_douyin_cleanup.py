import os
import tempfile
import unittest
import uuid
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from unittest.mock import Mock, patch

from douyin.cleanup import (
    cleanup_expired_files,
    ensure_storage_capacity,
    storage_usage_percent,
)
from douyin.cleanup_cli import main as cleanup_main
from douyin.config import settings
from douyin.errors import DouyinError
from douyin.jobs import utc_now


class _MemoryStore:
    def __init__(self, job_ids=()):
        self.job_ids = set(job_ids)
        self.deleted: list[str] = []

    def delete(self, job_id: str) -> bool:
        self.deleted.append(job_id)
        if job_id not in self.job_ids:
            return False
        self.job_ids.remove(job_id)
        return True


class CleanupTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.downloading = self.root / "downloading"
        self.ready = self.root / "ready"
        self.downloading.mkdir()
        self.ready.mkdir()
        self.config = replace(
            settings,
            downloading_dir=str(self.downloading),
            ready_dir=str(self.ready),
            part_ttl_seconds=900,
            ready_file_ttl_seconds=7200,
            disk_usage_limit_percent=80,
        )
        self.now = utc_now()

    def tearDown(self):
        self.directory.cleanup()

    @staticmethod
    def _job_id() -> str:
        return str(uuid.uuid4())

    def _file(self, root: Path, name: str, age_seconds: int) -> Path:
        path = root / name
        path.write_bytes(b"test")
        timestamp = (self.now - timedelta(seconds=age_seconds)).timestamp()
        os.utime(path, (timestamp, timestamp))
        return path

    def test_removes_only_expired_regular_files_and_corresponding_jobs(self):
        old_part_id = self._job_id()
        old_video_id = self._job_id()
        recent_part_id = self._job_id()
        old_part = self._file(self.downloading, f"{old_part_id}.part", 901)
        old_video = self._file(self.ready, f"{old_video_id}.mp4", 7201)
        recent_part = self._file(self.downloading, f"{recent_part_id}.part", 899)
        invalid = self._file(self.ready, "not-a-job.mp4", 9000)
        nested = self.ready / "nested"
        nested.mkdir()
        self._file(nested, f"{self._job_id()}.mp4", 9000)
        store = _MemoryStore({old_part_id, old_video_id, recent_part_id})

        result = cleanup_expired_files(self.config, store=store, now=self.now)

        self.assertFalse(old_part.exists())
        self.assertFalse(old_video.exists())
        self.assertTrue(recent_part.exists())
        self.assertTrue(invalid.exists())
        self.assertTrue(nested.exists())
        self.assertEqual(result.removed_parts, 1)
        self.assertEqual(result.removed_videos, 1)
        self.assertEqual(result.removed_jobs, 2)
        self.assertEqual(set(store.deleted), {old_part_id, old_video_id})

    def test_stale_part_does_not_delete_job_when_ready_video_exists(self):
        job_id = self._job_id()
        self._file(self.downloading, f"{job_id}.part", 901)
        ready = self._file(self.ready, f"{job_id}.mp4", 10)
        store = _MemoryStore({job_id})

        result = cleanup_expired_files(self.config, store=store, now=self.now)

        self.assertTrue(ready.exists())
        self.assertEqual(result.removed_parts, 1)
        self.assertEqual(result.removed_jobs, 0)
        self.assertEqual(store.deleted, [])

    def test_ignores_symlinks_and_is_idempotent(self):
        job_id = self._job_id()
        target = self._file(self.root, "outside.mp4", 9000)
        link = self.ready / f"{job_id}.mp4"
        link.symlink_to(target)
        store = _MemoryStore({job_id})

        first = cleanup_expired_files(self.config, store=store, now=self.now)
        second = cleanup_expired_files(self.config, store=store, now=self.now)

        self.assertTrue(link.is_symlink())
        self.assertTrue(target.exists())
        self.assertEqual(first.removed_videos, 0)
        self.assertEqual(second.removed_videos, 0)
        self.assertEqual(store.deleted, [])

    def test_rejects_relative_root_root_directory_and_symlink_root(self):
        store = _MemoryStore()
        with self.assertRaises(ValueError):
            cleanup_expired_files(
                replace(self.config, downloading_dir="relative/downloading"),
                store=store,
            )
        with self.assertRaises(ValueError):
            cleanup_expired_files(
                replace(self.config, ready_dir="/"),
                store=store,
            )
        with self.assertRaises(ValueError):
            cleanup_expired_files(
                replace(
                    self.config,
                    ready_dir=str(self.root / "child" / ".." / "ready"),
                ),
                store=store,
            )

        linked_root = self.root / "linked-ready"
        linked_root.symlink_to(self.ready, target_is_directory=True)
        with self.assertRaises(ValueError):
            cleanup_expired_files(
                replace(self.config, ready_dir=str(linked_root)),
                store=store,
            )

    @patch("douyin.cleanup.cleanup_expired_files")
    @patch("douyin.cleanup.storage_usage_percent", side_effect=[85.0, 74.0])
    def test_disk_guard_cleans_first_and_allows_recovered_volume(
        self,
        usage_percent: Mock,
        cleanup: Mock,
    ):
        store = _MemoryStore()
        result = ensure_storage_capacity(self.config, store=store)
        self.assertEqual(result, 74.0)
        cleanup.assert_called_once_with(self.config, store=store)
        self.assertEqual(usage_percent.call_count, 2)

    @patch("douyin.cleanup.cleanup_expired_files")
    @patch("douyin.cleanup.storage_usage_percent", side_effect=[85.0, 84.0])
    def test_disk_guard_rejects_when_cleanup_cannot_lower_usage(
        self,
        _usage_percent: Mock,
        cleanup: Mock,
    ):
        with self.assertRaises(DouyinError) as caught:
            ensure_storage_capacity(self.config, store=_MemoryStore())
        self.assertEqual(caught.exception.code, "DISK_PRESSURE")
        self.assertTrue(caught.exception.retryable)
        cleanup.assert_called_once()

    @patch("douyin.cleanup.shutil.disk_usage")
    def test_storage_usage_checks_both_fixed_directories(self, disk_usage: Mock):
        disk_usage.side_effect = [
            Mock(total=100, used=25),
            Mock(total=200, used=70),
        ]
        self.assertEqual(storage_usage_percent(self.config), 35.0)
        self.assertEqual(
            disk_usage.call_args_list,
            [unittest.mock.call(self.downloading), unittest.mock.call(self.ready)],
        )

    def test_cli_rejects_external_path_arguments(self):
        with patch("sys.argv", ["cleanup", "/tmp/untrusted"]):
            with self.assertRaises(SystemExit) as caught:
                cleanup_main()
        self.assertIn("does not accept", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
