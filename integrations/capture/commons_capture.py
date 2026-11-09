#!/usr/bin/env python3
"""Private, bounded delivery outbox for explicitly approved Commons captures.

This does not discover transcripts, run agents, or enable a vendor's hooks.
Only normalized commons.capture/1 envelopes are accepted.
"""
import argparse
import contextlib
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import random
import sqlite3
import stat
import time
import uuid
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

CONTRACT = "commons.capture/1"
MAX_BYTES = 32 * 1024 * 1024
MAX_BATCHES = 500
MAX_ATTEMPTS = 8


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                      allow_nan=False)


def source_key(source):
    if not isinstance(source, dict) or set(source) != {"provider", "namespace", "thread_id"}:
        raise ValueError("source requires provider, namespace and thread_id")
    if any(not isinstance(v, str) or not v.strip() or len(v) > 300 for v in source.values()):
        raise ValueError("source identities must be nonempty strings of at most 300 characters")
    return hashlib.sha256(canonical(source).encode()).hexdigest()


def origin(value):
    url = urlsplit(value)
    try:
        local = ipaddress.ip_address(url.hostname or "").is_loopback
    except ValueError:
        local = url.hostname == "localhost"
    if (not url.hostname or url.username or url.password or url.query or url.fragment
            or url.path not in ("", "/")
            or not (url.scheme == "https" or (url.scheme == "http" and local))):
        raise ValueError("destination must be an HTTPS origin (HTTP only on loopback)")
    return value.rstrip("/")


@contextlib.contextmanager
def database(directory):
    root = Path(directory).expanduser()
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    info = root.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise ValueError("state directory must be owner-only (0700), not a symlink")
    path = root / "delivery.sqlite3"
    if path.exists() or path.is_symlink():
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise ValueError("outbox must be an owner-only regular file")
    old_umask = os.umask(0o077)
    try:
        db = sqlite3.connect(path, timeout=15)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("PRAGMA foreign_keys=ON")
        db.executescript("""
          CREATE TABLE IF NOT EXISTS destination (
            singleton INTEGER PRIMARY KEY CHECK(singleton=1), origin TEXT NOT NULL,
            installation TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS sources (
            id TEXT PRIMARY KEY, identity TEXT NOT NULL, enabled INTEGER NOT NULL DEFAULT 0,
            deleted INTEGER NOT NULL DEFAULT 0, cursor TEXT, scope TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS batches (
            ordinal INTEGER PRIMARY KEY AUTOINCREMENT, source TEXT NOT NULL REFERENCES sources(id),
            id TEXT NOT NULL, hash TEXT NOT NULL, payload TEXT,
            state TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0,
            available REAL NOT NULL DEFAULT 0, error TEXT, chat_id TEXT,
            UNIQUE(source,id));
        """)
        yield db
    finally:
        if "db" in locals():
            db.close()
        os.umask(old_umask)


def initialize(db, url, installation):
    url = origin(url)
    if not installation.strip():
        raise ValueError("installation identity is required")
    with db:
        row = db.execute("SELECT * FROM destination").fetchone()
        if row and (row["origin"] != url or row["installation"] != installation):
            raise ValueError("outbox destination is immutable; use a separate state directory")
        db.execute("INSERT OR IGNORE INTO destination VALUES(1,?,?)", (url, installation))
    return {"initialized": True, **status(db)}


def set_enabled(db, source, enabled, scope=None):
    key = source_key(source)
    with db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute("SELECT * FROM sources WHERE id=?", (key,)).fetchone()
        if enabled:
            if not scope or not scope.strip():
                raise ValueError("explicit approved project/thread scope is required")
            if row and row["deleted"]:
                raise ValueError("deleted capture identity cannot be enabled again")
            if row and row["scope"] != scope:
                raise ValueError("scope is immutable; reconcile before changing capture")
            db.execute("INSERT OR IGNORE INTO sources(id,identity,scope) VALUES(?,?,?)",
                       (key, canonical(source), scope))
        db.execute("UPDATE sources SET enabled=? WHERE id=?", (int(enabled), key))
    return {"source": key, "enabled": enabled}


class OutboxFull(ValueError):
    """Retryable capacity pressure; the source cursor has not advanced."""


def enqueue(db, envelope, cursor=None, *, history_approved=False):
    if not isinstance(envelope, dict) or envelope.get("contract_version") != CONTRACT:
        raise ValueError("unsupported capture contract")
    key = source_key(envelope.get("source"))
    batch = envelope.get("batch_id")
    if not isinstance(batch, str) or not batch.strip() or len(batch) > 200:
        raise ValueError("stable batch_id required (1–200 characters)")
    if envelope.get("history", False) and not history_approved:
        raise ValueError("historical import requires explicit --approve-history")
    payload = canonical(envelope)
    digest = hashlib.sha256(payload.encode()).hexdigest()
    with db:
        db.execute("BEGIN IMMEDIATE")
        source = db.execute("SELECT * FROM sources WHERE id=?", (key,)).fetchone()
        if not source or not source["enabled"] or source["deleted"]:
            raise ValueError("capture is disabled or deleted for this exact source")
        prior = db.execute("SELECT * FROM batches WHERE source=? AND id=?", (key, batch)).fetchone()
        if prior:
            if prior["hash"] != digest:
                raise ValueError("batch identity already used for different content")
            return {"state": prior["state"], "duplicate": True}
        size, count = db.execute(
            "SELECT COALESCE(sum(length(CAST(payload AS BLOB))),0),count(payload) FROM batches"
        ).fetchone()
        if size + len(payload.encode()) > MAX_BYTES or count >= MAX_BATCHES:
            raise OutboxFull("outbox full; source cursor unchanged, capture needs attention")
        db.execute("INSERT INTO batches(source,id,hash,payload,state) VALUES(?,?,?,?,'queued')",
                   (key, batch, digest, payload))
        if cursor is not None:
            db.execute("UPDATE sources SET cursor=? WHERE id=?", (cursor, key))
    return {"state": "queued", "duplicate": False}


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def token_from(path):
    path = Path(path).expanduser()
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise ValueError("token file must be owner-only (0600), not a symlink")
    token = path.read_text().strip()
    if not 32 <= len(token) <= 4096 or any(c.isspace() for c in token):
        raise ValueError("invalid token file")
    return token


def purge_local(db, key):
    """Discard this source's local bodies; keep its replay barrier. No server deletion."""
    db.execute("UPDATE sources SET enabled=0,deleted=1,cursor=NULL WHERE id=?", (key,))
    db.execute("UPDATE batches SET state='deleted',payload=NULL,error=NULL WHERE source=?", (key,))


def flush(db, token, limit=20, *, source_keys=None):
    target = db.execute("SELECT * FROM destination").fetchone()
    if not target:
        raise ValueError("initialize the destination first")
    keys = None if source_keys is None else tuple(sorted(set(source_keys)))
    if keys is not None:
        if any(not isinstance(key, str) or len(key) != 64 or any(c not in '0123456789abcdef' for c in key) for key in keys):
            raise ValueError('invalid checked source identity')
        if not keys:
            return {"delivered": 0, **status(db)}
    source_filter = '' if keys is None else ' AND b.source IN (' + ','.join('?' for _ in keys) + ')'
    opener = build_opener(ProxyHandler({}), NoRedirect())
    delivered = 0
    for _ in range(limit):
        # Serializes flush/disable/queue; no later delivery can begin after disable commits.
        with db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(f"""
              SELECT b.* FROM batches b JOIN sources s ON s.id=b.source
              WHERE s.enabled=1 AND s.deleted=0 AND b.state='queued' AND b.available<=?
              {source_filter}
              AND NOT EXISTS(SELECT 1 FROM batches older WHERE older.source=b.source
                AND older.ordinal<b.ordinal AND older.state IN ('queued','failed'))
              ORDER BY b.ordinal LIMIT 1
            """, (time.time(), *(keys or ()))).fetchone()
            if row is None:
                break
            request = Request(target["origin"] + "/api/capture", method="POST",
                              data=row["payload"].encode(), headers={
                                  "Authorization": "Bearer " + token,
                                  "Content-Type": "application/json"})
            error, retry, deleted = None, False, False
            try:
                with opener.open(request, timeout=10) as response:
                    body = response.read(65537)
                    if len(body) > 65536:
                        raise ValueError("oversize acknowledgement")
                    result = json.loads(body)
                    chat_id = result["chat_id"]
                    if not isinstance(chat_id, str) or str(uuid.UUID(chat_id)) != chat_id:
                        raise ValueError("invalid acknowledgement")
                db.execute("UPDATE batches SET state='acknowledged',payload=NULL,error=NULL,chat_id=? WHERE ordinal=?",
                           (chat_id, row["ordinal"]))
                delivered += 1
                continue
            except HTTPError as exc:
                error = "HTTP " + str(exc.code)
                retry = exc.code in (408, 429) or 500 <= exc.code < 600
                deleted = exc.code == 410
                exc.close()
            except (URLError, TimeoutError, OSError):
                error, retry = "delivery unavailable", True
            except (ValueError, KeyError, TypeError):
                error, retry = "invalid acknowledgement; reconcile delivery", True
            if deleted:
                purge_local(db, row["source"])
            else:
                attempts = row["attempts"] + 1
                state = "queued" if retry and attempts < MAX_ATTEMPTS else "failed"
                delay = min(300, 2 ** attempts) * random.uniform(.8, 1.2)
                db.execute("UPDATE batches SET state=?,attempts=?,available=?,error=? WHERE ordinal=?",
                           (state, attempts, time.time() + delay, error, row["ordinal"]))
                if error in ("HTTP 401", "HTTP 403"):
                    # No more requests using a credential known to be denied.
                    break
    return {"delivered": delivered, **status(db)}


def retry(db, source, batch):
    """Explicit reconciliation after an operator fixes a terminal delivery failure."""
    key = source_key(source)
    with db:
        db.execute("BEGIN IMMEDIATE")
        source = db.execute("SELECT * FROM sources WHERE id=?", (key,)).fetchone()
        if not source or not source["enabled"] or source["deleted"]:
            raise ValueError("capture is disabled or deleted")
        changed = db.execute("""
            UPDATE batches SET state='queued',attempts=0,available=0,error=NULL
            WHERE source=? AND id=? AND state='failed' AND payload IS NOT NULL
        """, (key, batch)).rowcount
        if not changed:
            raise ValueError("no failed batch to retry")
    return {"state": "queued"}


def status(db):
    # Never print transcripts, tokens, provider namespaces or source paths.
    return {"sources": [dict(row) for row in db.execute(
        "SELECT id,enabled,deleted FROM sources ORDER BY id")],
        "batches": [dict(row) for row in db.execute(
            "SELECT source,id,state,attempts,error,chat_id FROM batches ORDER BY ordinal")],
        "pending_bytes": db.execute(
            "SELECT COALESCE(sum(length(CAST(payload AS BLOB))),0) FROM batches").fetchone()[0]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state", required=True, help="private per-installation/provider/host state directory")
    commands = parser.add_subparsers(dest="command", required=True)
    init = commands.add_parser("init")
    init.add_argument("--url", required=True)
    init.add_argument("--installation", required=True)
    for name in ("enable", "disable", "retry", "purge-local"):
        sub = commands.add_parser(name)
        sub.add_argument("--provider", required=True)
        sub.add_argument("--namespace", required=True)
        sub.add_argument("--thread", required=True)
        if name == "retry":
            sub.add_argument("--batch", required=True)
        if name == "enable":
            sub.add_argument("--scope", required=True)
            sub.add_argument("--acknowledge-shared-readership", action="store_true", required=True)
    queue = commands.add_parser("enqueue")
    queue.add_argument("file", type=Path)
    queue.add_argument("--cursor")
    queue.add_argument("--approve-history", action="store_true")
    send = commands.add_parser("flush")
    send.add_argument("--token-file", required=True)
    commands.add_parser("status")
    args = parser.parse_args()
    try:
        with database(args.state) as db:
            if args.command == "init":
                result = initialize(db, args.url, args.installation)
            elif args.command in ("enable", "disable"):
                result = set_enabled(db, {"provider": args.provider, "namespace": args.namespace,
                                          "thread_id": args.thread}, args.command == "enable",
                                     getattr(args, "scope", None))
            elif args.command == "enqueue":
                if args.file.stat().st_size > MAX_BYTES:
                    raise ValueError("envelope exceeds outbox capacity")
                result = enqueue(db, json.loads(args.file.read_text()), args.cursor,
                                 history_approved=args.approve_history)
            elif args.command == "flush":
                result = flush(db, token_from(args.token_file))
            elif args.command == "retry":
                result = retry(db, {"provider": args.provider, "namespace": args.namespace,
                                    "thread_id": args.thread}, args.batch)
            elif args.command == "purge-local":
                with db:
                    db.execute("BEGIN IMMEDIATE")
                    key = source_key({"provider": args.provider, "namespace": args.namespace,
                                      "thread_id": args.thread})
                    if not db.execute("SELECT 1 FROM sources WHERE id=?", (key,)).fetchone():
                        raise ValueError("unknown local source")
                    purge_local(db, key)
                result = {"local_source_discarded": True, "server_deleted": False, **status(db)}
            else:
                result = status(db)
        print(canonical(result))
    except (ValueError, OSError, sqlite3.Error) as exc:
        # Do not echo arbitrary parser/source/network payloads in logs.
        print(canonical({"error": str(exc) if isinstance(exc, ValueError)
                         and not isinstance(exc, json.JSONDecodeError) else "capture operation failed"}))
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
