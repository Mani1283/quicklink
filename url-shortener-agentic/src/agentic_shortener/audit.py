"""Append-only JSONL audit mirror with a hash chain for tamper evidence."""

import hashlib
import json
import os
import threading
from contextlib import contextmanager
from pathlib import Path


class JsonlAuditLog:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._last_hash = self._read_last_hash()

    def append(self, event: dict) -> dict:
        with self._lock:
            with self._file_lock():
                previous = self._tail_hash()
                payload = {"previous_hash": previous, "event": event}
                canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
                event_hash = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
                record = {**payload, "event_hash": event_hash}
                with self.path.open("a", encoding="utf-8", newline="\n") as stream:
                    stream.write(json.dumps(record, sort_keys=True, ensure_ascii=False) + "\n")
                    stream.flush()
                    os.fsync(stream.fileno())
                self._last_hash = event_hash
                return record

    def verify(self) -> tuple[bool, int, str | None]:
        with self._lock, self._file_lock():
            return self._verify_unlocked()

    def _read_last_hash(self) -> str:
        if not self.path.exists():
            return "0" * 64
        with self._file_lock():
            valid, _, error = self._verify_unlocked()
        if not valid:
            raise ValueError(f"audit log failed hash-chain verification: {error}")
        return self._tail_hash()

    def _tail_hash(self) -> str:
        try:
            if not self.path.exists():
                return "0" * 64
            with self.path.open("rb") as stream:
                stream.seek(0, os.SEEK_END)
                end = stream.tell()
                if end == 0:
                    return "0" * 64
                position = end - 1
                while position >= 0:
                    stream.seek(position)
                    if stream.read(1) == b"\n" and position != end - 1:
                        break
                    position -= 1
                stream.seek(position + 1 if position >= 0 else 0)
                record = json.loads(stream.readline().decode("utf-8"))
                last = record["event_hash"]
        except (OSError, json.JSONDecodeError, KeyError) as exc:
            raise ValueError(f"audit log is corrupt: {self.path}") from exc
        if len(last) != 64:
            raise ValueError(f"audit log has invalid tail hash: {self.path}")
        return last

    def _verify_unlocked(self) -> tuple[bool, int, str | None]:
        previous = "0" * 64
        count = 0
        if not self.path.exists():
            return True, 0, None
        try:
            with self.path.open("r", encoding="utf-8") as stream:
                for line_number, line in enumerate(stream, 1):
                    record = json.loads(line)
                    if record.get("previous_hash") != previous:
                        return False, line_number, "previous hash mismatch"
                    payload = {"previous_hash": previous, "event": record["event"]}
                    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
                    expected = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
                    if record.get("event_hash") != expected:
                        return False, line_number, "event hash mismatch"
                    previous = expected
                    count += 1
        except (OSError, json.JSONDecodeError, KeyError) as exc:
            return False, count + 1, str(exc)
        return True, count, None

    @contextmanager
    def _file_lock(self):
        lock_path = self.path.with_name(self.path.name + ".lock")
        with lock_path.open("a+b") as stream:
            if os.name == "nt":
                import msvcrt
                stream.seek(0, os.SEEK_END)
                if stream.tell() == 0:
                    stream.write(b"\0")
                    stream.flush()
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_LOCK, 1)
                try:
                    yield
                finally:
                    stream.seek(0)
                    msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
                try:
                    yield
                finally:
                    fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
