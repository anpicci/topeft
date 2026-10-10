"""Owned manager staging and free-space guard for opt-in Work Queue runs.

The watchdog is a separate process so a blocked executor event loop cannot
prevent polling. It deliberately uses SIGTERM: Coffea 0.7.22 reserves SIGINT
for a final accumulation. A stopped run retains staging for operator review.
"""

import json
import argparse
import math
import multiprocessing
import os
from pathlib import Path
import re
import signal
import stat
import subprocess
import threading


class staging_guard_error(RuntimeError):
    pass


def _process_start(pid):
    try:
        return Path(f"/proc/{pid}/stat").read_text().rsplit(") ", 1)[1].split()[19]
    except FileNotFoundError:
        return None
    except (OSError, IndexError) as error:
        raise staging_guard_error("manager process identity cannot be read") from error


def _quota_available(quota_root):
    if not quota_root or not quota_root.startswith(("/groups/", "/users/")):
        raise staging_guard_error("an exact supported quota root is required")
    result = subprocess.run(
        ["quota", quota_root], capture_output=True, text=True, timeout=15,
        check=False,
    )
    if result.returncode or len(result.stdout.splitlines()) != 2:
        raise staging_guard_error("quota headroom could not be measured")
    fields = result.stdout.splitlines()[1].split()
    if len(fields) != 5 or fields[0] != quota_root:
        raise staging_guard_error("quota result does not match the declared root")
    value = fields[4]
    # The site prints rounded human units. Decimal multipliers provide a
    # conservative lower estimate if its display uses binary units.
    suffixes = {"K": 1000, "M": 1000 ** 2, "G": 1000 ** 3, "T": 1000 ** 4}
    try:
        if value[-1:] in suffixes:
            return int(float(value[:-1]) * suffixes[value[-1]])
        return int(value)
    except ValueError as error:
        raise staging_guard_error("quota headroom is not numeric") from error


def _space(base, quota_root):
    values = os.statvfs(base)
    free_bytes = values.f_bavail * values.f_frsize
    free_inodes = values.f_favail
    quota_bytes = _quota_available(quota_root)
    return min(free_bytes, quota_bytes), free_inodes


def _validate_base(base):
    path = Path(base)
    if not path.is_absolute() or not path.is_dir():
        raise staging_guard_error("staging base must be an existing absolute directory")
    for component in (path, *path.parents):
        if component.is_symlink():
            raise staging_guard_error("staging path has a symlink component")
    real = path.resolve(strict=True)
    if real == Path("/tmp") or real == Path("/var/tmp") or any(
        parent in (Path("/tmp"), Path("/var/tmp")) for parent in real.parents
    ):
        raise staging_guard_error("root temporary staging is forbidden")
    if os.stat(real).st_uid != os.getuid() or not os.access(real, os.W_OK | os.X_OK):
        raise staging_guard_error("staging base ownership or write access is invalid")
    mount = real
    while mount.parent != mount and os.stat(mount.parent).st_dev == os.stat(mount).st_dev:
        mount = mount.parent
    if mount == Path("/"):
        raise staging_guard_error("root-backed staging is forbidden")
    return real


def _local_readers(path, max_processes=32768):
    scanned = 0
    prefix = str(path) + os.sep
    for item in Path("/proc").iterdir():
        if not item.name.isdigit():
            continue
        scanned += 1
        if scanned > max_processes:
            raise staging_guard_error("local reader scan limit exceeded")
        try:
            if item.stat().st_uid != os.getuid():
                continue
            for descriptor in (item / "fd").iterdir():
                target = os.readlink(descriptor)
                if target == str(path) or target.startswith(prefix):
                    return True
        except FileNotFoundError:
            continue
        except PermissionError as error:
            raise staging_guard_error("local reader state is inaccessible") from error
    return False


def _charged_tree(path, max_entries=100000):
    total_bytes = 0
    entries = 0
    pending = [path]
    while pending:
        current = pending.pop()
        try:
            with os.scandir(current) as children:
                for child in children:
                    entries += 1
                    if entries > max_entries:
                        raise staging_guard_error("staging entry scan limit exceeded")
                    try:
                        info = child.stat(follow_symlinks=False)
                    except FileNotFoundError:
                        # Coffea may remove an accumulated child after scandir
                        # yielded it. The next bounded poll measures again.
                        continue
                    if stat.S_ISLNK(info.st_mode):
                        raise staging_guard_error("symlink in owned staging tree")
                    total_bytes += info.st_blocks * 512
                    if stat.S_ISDIR(info.st_mode):
                        pending.append(child.path)
        except FileNotFoundError:
            if os.fspath(current) == os.fspath(path):
                raise
            # A queued intermediate directory can disappear after its stat.
            continue
    return total_bytes, entries


def _verify_owned_tree(path, marker, owner_pid, owner_start, owner_inode, marker_inode):
    root_info = os.lstat(path)
    marker_info = os.lstat(marker)
    if (not stat.S_ISDIR(root_info.st_mode)
            or stat.S_ISLNK(root_info.st_mode)
            or root_info.st_ino != owner_inode
            or root_info.st_uid != os.getuid()
            or not stat.S_ISREG(marker_info.st_mode)
            or marker_info.st_ino != marker_inode
            or marker_info.st_uid != os.getuid()):
        raise staging_guard_error("staging root or marker identity changed")
    metadata = json.loads(marker.read_text())
    if (metadata.get("path") != os.fspath(path)
            or metadata.get("owner_inode") != owner_inode
            or metadata.get("owner_uid") != os.getuid()
            or metadata.get("owner_pid") != owner_pid
            or metadata.get("owner_start") != owner_start
            or metadata.get("status") != "running"):
        raise staging_guard_error("staging owner marker changed")


def _watch(path, base, quota_root, owner_pid, owner_start, warning_bytes,
           poll_seconds, stop_event, owner_inode,
           marker_inode):
    marker = Path(path) / "guard.json"
    while not stop_event.is_set():
        if _process_start(owner_pid) != owner_start:
            return
        try:
            _verify_owned_tree(path, marker, owner_pid, owner_start, owner_inode, marker_inode)
            charged_bytes, entries = _charged_tree(path)
            available_bytes, free_inodes = _space(base, quota_root)
            _verify_owned_tree(path, marker, owner_pid, owner_start, owner_inode, marker_inode)
            print(f"Work Queue staging health: available_bytes={available_bytes} "
                  f"free_inodes={free_inodes} charged_bytes={charged_bytes} "
                  f"entries={entries}", flush=True)
            if available_bytes < warning_bytes or free_inodes < 1000:
                print("WARNING: Work Queue staging free space or inodes are low; "
                      "manager remains running", flush=True)
        except Exception as error:
            try:
                metadata = json.loads(marker.read_text())
                metadata.update(status="cleanup_needed", reason="measurement_failed",
                                detail=str(error)[:240])
                marker.write_text(json.dumps(metadata) + "\n")
            finally:
                if _process_start(owner_pid) == owner_start:
                    os.kill(owner_pid, signal.SIGTERM)
            return
        stop_event.wait(poll_seconds)


def start_guard(base, invocation, quota_root, warning_bytes, min_free_bytes,
                poll_seconds):
    if signal.getsignal(signal.SIGTERM) != signal.SIG_DFL:
        raise staging_guard_error("SIGTERM has a custom handler; safe stop unproven")
    if not invocation or invocation in (".", "..") or Path(invocation).name != invocation:
        raise staging_guard_error("invocation must be one path component")
    if not (10000000000 <= min_free_bytes <= warning_bytes
            and math.isfinite(poll_seconds) and poll_seconds > 0):
        raise staging_guard_error("invalid free-space warning/minimum/poll configuration")
    real_base = _validate_base(base)
    if not quota_root or not quota_root.startswith(("/groups/", "/users/")):
        raise staging_guard_error("an exact site quota root is required")
    if os.path.commonpath((str(real_base), quota_root)) != quota_root:
        raise staging_guard_error("quota root does not own the selected staging base")
    available, free_inodes = _space(real_base, quota_root)
    if available < min_free_bytes or free_inodes < 1000:
        raise staging_guard_error("minimum free space or protective inode reserve unavailable")
    path = real_base / invocation
    path.mkdir(mode=0o700)
    if stat.S_IMODE(path.stat().st_mode) != 0o700:
        path.rmdir()
        raise staging_guard_error("invocation staging mode is not 0700")
    owner_inode = path.stat().st_ino
    owner_pid = os.getpid()
    owner_start = _process_start(owner_pid)
    if owner_start is None:
        raise staging_guard_error("manager process identity unavailable")
    marker = path / "guard.json"
    marker.write_text(json.dumps({"status": "running", "path": str(path),
                                  "owner_uid": os.getuid(), "owner_pid": owner_pid,
                                  "owner_start": owner_start, "owner_inode": owner_inode,
                                  "invocation": invocation}) + "\n")
    marker_inode = marker.stat().st_ino
    context = multiprocessing.get_context("spawn")
    stop_event = context.Event()
    watchdog = context.Process(target=_watch, args=(str(path), str(real_base), quota_root,
        owner_pid, owner_start, warning_bytes,
        poll_seconds, stop_event, owner_inode, marker_inode), daemon=False)
    try:
        watchdog.start()
    except Exception as error:
        marker.write_text(json.dumps({"status": "cleanup_needed", "reason": "watchdog_start_failed",
                                      "path": str(path), "owner_inode": owner_inode,
                                      "owner_uid": os.getuid(), "owner_pid": owner_pid,
                                      "owner_start": owner_start}) + "\n")
        raise staging_guard_error("watchdog failed before Work Queue startup") from error
    if not watchdog.is_alive():
        raise staging_guard_error("watchdog failed before Work Queue startup")

    def check_watchdog():
        while not stop_event.wait(min(poll_seconds, 1)):
            if not watchdog.is_alive():
                if os.getpid() == owner_pid:
                    os.kill(os.getpid(), signal.SIGTERM)
                return

    thread = threading.Thread(target=check_watchdog, daemon=True)
    thread.start()
    return path, owner_inode, stop_event, watchdog


def finish_guard(path, owner_inode, stop_event, watchdog, succeeded):
    stop_event.set()
    watchdog.join(timeout=10)
    if watchdog.is_alive() or watchdog.exitcode != 0:
        raise staging_guard_error("watchdog did not stop cleanly; cleanup_needed")
    marker = path / "guard.json"
    if path.is_symlink() or path.stat().st_ino != owner_inode or path.stat().st_uid != os.getuid():
        raise staging_guard_error("staging owner/path changed; cleanup_needed")
    try:
        metadata = json.loads(marker.read_text())
    except (OSError, ValueError) as error:
        raise staging_guard_error("staging ownership marker unavailable; cleanup_needed") from error
    if (metadata.get("status") != "running" or metadata.get("path") != str(path)
            or metadata.get("owner_inode") != owner_inode):
        raise staging_guard_error("staging marker changed during manager execution; cleanup_needed")
    if not succeeded:
        metadata.update(status="cleanup_needed", reason="manager_failed")
        marker.write_text(json.dumps(metadata) + "\n")
        return
    metadata.update(status="completed_pending_receipt")
    marker.write_text(json.dumps(metadata) + "\n")


def cleanup_owned_staging(path):
    """Called only after campaign state and native logs record source completion."""
    path = Path(path)
    marker = path / "guard.json"
    try:
        metadata = json.loads(marker.read_text())
        info = path.lstat()
    except (OSError, ValueError) as error:
        raise staging_guard_error("staging ownership evidence unavailable") from error
    if (not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid()
            or info.st_ino != metadata.get("owner_inode")
            or metadata.get("owner_uid") != os.getuid()
            or metadata.get("path") != str(path)
            or metadata.get("status") != "completed_pending_receipt"
            or not isinstance(metadata.get("owner_pid"), int)
            or not isinstance(metadata.get("owner_start"), str)):
        raise staging_guard_error("staging owner/path/status does not match the completed invocation")
    for component in path.parents:
        if component.is_symlink():
            raise staging_guard_error("staging parent gained a symlink; cleanup_needed")
    try:
        owner_start = _process_start(metadata.get("owner_pid"))
    except staging_guard_error:
        metadata.update(status="cleanup_needed", reason="manager_liveness_unknown")
        marker.write_text(json.dumps(metadata) + "\n")
        raise
    if owner_start == metadata.get("owner_start"):
        metadata.update(status="cleanup_needed", reason="manager_still_live")
        marker.write_text(json.dumps(metadata) + "\n")
        raise staging_guard_error("manager process is still live")
    if _local_readers(path):
        metadata.update(status="cleanup_needed", reason="local_reader_active")
        marker.write_text(json.dumps(metadata) + "\n")
        raise staging_guard_error("local staging reader remains active")
    def reject_cleanup(reason):
        metadata.update(status="cleanup_needed", reason=reason)
        marker.write_text(json.dumps(metadata) + "\n")
        raise staging_guard_error(f"{reason}; cleanup_needed")

    # Coffea normally removes its TemporaryDirectory on exit. If it remains,
    # remove only its recognized, owned regular files after checking the whole
    # directory. Unknown entries keep the invocation available for review.
    children = [child for child in path.iterdir() if child.name != "guard.json"]
    files = []
    if children:
        if (len(children) != 1 or not re.fullmatch(r"tmp[a-z0-9_]+wq-tmp-", children[0].name)):
            reject_cleanup("unexpected owned staging entry")
        temporary = children[0]
        temporary_info = temporary.lstat()
        if (not stat.S_ISDIR(temporary_info.st_mode) or temporary_info.st_uid != os.getuid()
                or stat.S_IMODE(temporary_info.st_mode) != 0o700):
            reject_cleanup("Coffea temporary directory identity is uncertain")
        with os.scandir(temporary) as entries:
            for entry in entries:
                if len(files) >= 100000:
                    reject_cleanup("Coffea temporary directory scan limit exceeded")
                info = entry.stat(follow_symlinks=False)
                name = entry.name
                recognized = (re.fullmatch(r"(?:args_|out_|stdout_)[A-Za-z0-9_]+\.p", name)
                              or re.fullmatch(r"fn_wrapper[a-z0-9_]+", name)
                              or re.fullmatch(r"(?:preproc|proc|accum)[a-z0-9_]+\.p", name))
                if not recognized or not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_nlink != 1:
                    reject_cleanup("unknown or foreign Coffea staging file")
                files.append((Path(entry.path), info.st_ino))
        if _local_readers(temporary):
            reject_cleanup("local Coffea staging reader remains active")
        for file_path, inode in files:
            if file_path.lstat().st_ino != inode:
                reject_cleanup("Coffea staging file identity changed")
            file_path.unlink()
        if temporary.lstat().st_ino != temporary_info.st_ino:
            reject_cleanup("Coffea temporary directory identity changed")
        temporary.rmdir()
    marker.unlink()
    path.rmdir()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Finalize one completed owned Work Queue staging directory")
    parser.add_argument("action", choices=("cleanup",))
    parser.add_argument("path")
    arguments = parser.parse_args()
    try:
        cleanup_owned_staging(arguments.path)
    except staging_guard_error as error:
        parser.exit(1, f"cleanup_needed: {error}\n")
