#!/usr/bin/env python3
"""Transfer reviewed, normalized Context sample packages through Commons' API.

No source discovery, arbitrary file fetching, credential import, or capture activation.
Run on the source host; packages and checkpoints contain private material.
"""
import argparse
import base64
import collections
import fcntl
import getpass
import hashlib
import http.cookiejar
import ipaddress
import json
import os
from pathlib import Path
import sqlite3
import stat
import sys
import uuid
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, HTTPCookieProcessor, ProxyHandler, Request, build_opener

VERSION = "commons.context-sample/1"
FULL_VERSION = "commons.context-full/1"
LIMIT = 32 * 1024 * 1024


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode()


def digest(data):
    return hashlib.sha256(data).hexdigest()


def check_snapshot(snapshot):
    """Require explicit operator evidence; this does not establish the writer fence."""
    if (snapshot.get("kind") not in ("isolated_restore", "quiesced_source")
            or not isinstance(snapshot.get("backup_sha256"), str)
            or len(snapshot["backup_sha256"]) != 64
            or any(c not in "0123456789abcdef" for c in snapshot["backup_sha256"])
            or not isinstance(snapshot.get("writer_fence"), str)
            or not snapshot["writer_fence"].strip()):
        raise ValueError("full transfer requires verified backup identity and explicit writer-fence evidence")


def private(path, directory=False):
    info = path.lstat()
    correct_type = stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode)
    if not correct_type or info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise ValueError("private inputs/state must be owner-only and not symlinks")


def origin(value):
    url = urlsplit(value)
    try:
        local = ipaddress.ip_address(url.hostname or "").is_loopback
    except ValueError:
        local = url.hostname == "localhost"
    if (not url.hostname or url.username or url.password or url.query or url.fragment
            or url.path not in ("", "/")
            or not (url.scheme == "https" or (url.scheme == "http" and local))):
        raise ValueError("destination must be an HTTPS origin, or HTTP loopback")
    return value.rstrip("/")


def identity(record):
    kind = record["type"]
    if kind in ("object", "category", "chat"):
        value = record[kind]["id"]
    elif kind == "message":
        value = record["message"]["item"]["id"]
    elif kind == "run":
        value = record["run"]["run"]["id"]
    elif kind == "routine_result":
        value = record["original"]["id"]
    elif kind in ("artifact", "connection", "history", "correction"):
        value = record["id"]
    else:
        raise ValueError("unsupported record type; no records omitted")
    if str(uuid.UUID(value)) != value:
        raise ValueError("record identities must be canonical UUIDs")
    return kind, value


def envelope(store, package_hash, group):
    return dict(contract_version="commons/0.1",
                idempotency_key="context-sample:" + digest(encoded([package_hash, group["id"]])),
                operations=[dict(op="import_record", source_store=store, record=r)
                            for r in group["records"]])


def plan(package):
    """Order explicit atomic dependency groups; never split a Source/current-Artifact pair."""
    if (package["version"], package["scope"]) not in ((VERSION, "sample"), (FULL_VERSION, "full")):
        raise ValueError("explicit versioned sample or full package required")
    if package["scope"] == "full":
        evidence = package["source_evidence"]
        check_snapshot(evidence["snapshot"])
        counts = evidence["selected_counts"]
        if (evidence["consistency"] != "fenced_full_snapshot_two_equal_observations"
                or evidence["opening_catalog"] != evidence["closing_catalog"]
                or counts != {t: v["row_count"] for t, v in evidence["opening_catalog"].items()}
                or evidence["observed_counts"] != [counts, counts]):
            raise ValueError("full snapshot counts/schema/observations disagree")
    for key in ("source_store", "source_revision", "snapshot_id"):
        if not isinstance(package[key], str) or not package[key].strip():
            raise ValueError("source identity, revision and snapshot identity are required")
    if len(package["source_store"].encode()) > 200:
        raise ValueError("source_store exceeds destination limit")
    target = package["destination"]
    if origin(target["origin"]) != target["origin"]:
        raise ValueError("destination origin must be normalized")
    uuid.UUID(target["admin_user_id"])
    groups = package["groups"]
    if not groups:
        raise ValueError("empty sample")
    by_id, identities = {}, set()
    counts = collections.Counter()
    for group in groups:
        gid = group["id"]
        if not isinstance(gid, str) or not gid or gid in by_id:
            raise ValueError("atomic group IDs must be nonempty and unique")
        by_id[gid] = group
        if not 1 <= len(group["records"]) <= 50:
            raise ValueError("atomic group requires 1–50 records; cannot safely split it")
        for record in group["records"]:
            key = identity(record)
            if key in identities:
                raise ValueError("duplicate source record identity")
            identities.add(key)
            counts[key[0]] += 1
            if key[0] == "artifact":
                artifact = record["artifact"]
                if artifact.get("image_base64") is not None:
                    data = base64.b64decode(artifact["image_base64"], validate=True)
                elif artifact.get("body") is not None:
                    data = artifact["body"].encode()
                else:
                    data = (artifact.get("uri") or "").encode()
                if digest(data) != record["sha256"]:
                    raise ValueError("Artifact checksum mismatch")
    if dict(counts) != package["record_counts"]:
        raise ValueError("record counts disagree with package; no partial admission")
    # Stable across producer input order. The full manifest hash still fences edits.
    pending = set(by_id)
    ordered = []
    while pending:
        ready = sorted(gid for gid in pending
                       if all(dep in by_id and dep not in pending
                              for dep in by_id[gid]["depends_on"]))
        if not ready:
            raise ValueError("missing dependency or dependency cycle")
        for gid in ready:
            ordered.append(by_id[gid])
            pending.remove(gid)
    package_hash = digest(encoded(package))
    for group in ordered:
        if len(encoded(envelope(package["source_store"], package_hash, group))) > LIMIT:
            raise ValueError("atomic group exceeds 32 MiB; reconcile its dependencies")
    return package_hash, ordered


def load_package(directory):
    root = Path(directory).expanduser()
    private(root, directory=True)
    manifest = root / "package.json"
    private(manifest)
    package = json.loads(manifest.read_bytes())
    plan(package)
    seen = set()
    for entry in package["files"]:
        # Original references may be opaque/absolute. Only explicitly packaged paths are read.
        if not entry["reference"] or not entry["reason"]:
            raise ValueError("every file reference requires its original reference and disposition reason")
        if entry["status"] != "packaged":
            if entry["status"] not in ("missing", "unresolved", "excluded", "out_of_sample"):
                raise ValueError("unknown file disposition")
            if "path" in entry:
                raise ValueError("unavailable/excluded file must not supply packaged bytes")
            continue
        relative = Path(entry["path"])
        if relative.is_absolute() or ".." in relative.parts or not relative.parts:
            raise ValueError("packaged files must stay inside the private package")
        path = root
        for part in relative.parts[:-1]:
            path = path / part
            private(path, directory=True)
        path = path / relative.name
        private(path)
        if str(relative) in seen:
            raise ValueError("duplicate packaged file path")
        seen.add(str(relative))
        data = path.read_bytes()
        if len(data) != entry["size_bytes"] or digest(data) != entry["sha256"]:
            raise ValueError("packaged file checksum/size mismatch")
    return package


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


class Session:
    def __init__(self, url):
        self.origin = origin(url)
        self.opener = build_opener(ProxyHandler({}), NoRedirect(),
                                  HTTPCookieProcessor(http.cookiejar.CookieJar()))

    def request(self, route, body=None):
        request = Request(self.origin + "/api/" + route,
                          data=encoded(body) if body is not None else None,
                          headers={"Content-Type": "application/json", "Origin": self.origin})
        try:
            with self.opener.open(request, timeout=60) as response:
                return json.load(response)
        except HTTPError as error:
            # Server errors can echo private payload fragments. Report only the status.
            raise RuntimeError(f"HTTP {error.code}; stopped, reconcile before resuming") from None
        except (URLError, TimeoutError):
            raise RuntimeError("connection interrupted; outcome unknown, resume identical package") from None

    def login(self, username, password):
        self.request("login", dict(username=username, password=password))


def transfer(package, directory, session, replay=False):
    package_hash, groups = plan(package)
    target = package["destination"]
    if session.origin != target["origin"]:
        raise ValueError("session origin differs from the reviewed destination")
    actor = session.request("me")
    if actor["id"] != target["admin_user_id"] or actor["role"] != "admin" or actor["mode"] != "session":
        raise ValueError("destination requires its explicitly resolved administrator session")
    root = Path(directory).expanduser()
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    private(root, directory=True)
    path = root / "checkpoint.sqlite3"
    if path.exists() or path.is_symlink():
        private(path)
    # Serialize checkpoint users for the whole transfer, including HTTP calls.
    lock = os.open(root / "lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        old_umask = os.umask(0o077)
        try:
            db = sqlite3.connect(path)
        finally:
            os.umask(old_umask)
        try:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS binding (id INTEGER PRIMARY KEY CHECK(id=1), hash TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS acknowledged (id TEXT PRIMARY KEY);
            """)
            prior = db.execute("SELECT hash FROM binding").fetchone()
            if prior and prior[0] != package_hash:
                raise ValueError("checkpoint binds another package/source/destination; no overwrite")
            with db:
                db.execute("INSERT OR IGNORE INTO binding VALUES(1,?)", (package_hash,))
            sent = skipped = 0
            for group in groups:
                if not replay and db.execute("SELECT 1 FROM acknowledged WHERE id=?", (group["id"],)).fetchone():
                    skipped += 1
                    continue
                result = session.request("apply", envelope(package["source_store"], package_hash, group))
                expected = [identity(record)[1] for record in group["records"]]
                if (result.get("validated_only") is not False
                        or [change.get("id") for change in result.get("changes", [])] != expected):
                    raise RuntimeError("unexpected receipt; outcome unknown, no checkpoint advanced")
                with db:
                    db.execute("INSERT OR IGNORE INTO acknowledged VALUES(?)", (group["id"],))
                sent += 1
            return dict(acknowledged_groups=sent, checkpoint_skipped_groups=skipped,
                        record_counts=package["record_counts"], package_sha256=package_hash)
        finally:
            db.close()
    finally:
        os.close(lock)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("package", help="private directory containing package.json and explicit files")
    parser.add_argument("--state", help="private checkpoint directory; required to send")
    parser.add_argument("--username", default="admin")
    parser.add_argument("--send", action="store_true", help="send this approved sample; default only checks local packaging")
    parser.add_argument("--replay", action="store_true", help="send every group again after destination recovery")
    args = parser.parse_args()
    try:
        package = load_package(args.package)
        package_hash, groups = plan(package)
        if not args.send:
            print(json.dumps(dict(local_package_valid=True, groups=len(groups),
                                  record_counts=package["record_counts"], package_sha256=package_hash)))
            return
        if not args.state:
            raise ValueError("--state required")
        session = Session(package["destination"]["origin"])
        session.login(args.username, getpass.getpass("Destination administrator password (not saved): "))
        print(json.dumps(transfer(package, args.state, session, args.replay)))
    except RuntimeError as error:
        # These messages are generated locally; HTTP response bodies are never included.
        print(str(error), file=sys.stderr)
        sys.exit(1)
    except (ValueError, KeyError, TypeError, OSError, sqlite3.Error):
        # Do not print paths, records, credentials or server error bodies to shared logs.
        print("Transfer stopped. Check package shape/checksums, private permissions, destination/session, "
              "dependencies and conflicts locally. No failed group was acknowledged.", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
