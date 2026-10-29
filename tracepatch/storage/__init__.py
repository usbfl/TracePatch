"""SQLite action journal. Deterministic replay reconstructs state without new events.

Pending offline actions keep their reservation and action ID across restarts.
Only this module owns budget mutations; callbacks run after reservation commits.
"""
import json
import os
import base64
import sqlite3
import time
from pathlib import Path
from ..common import canonical, digest


class BudgetExhausted(Exception): pass
class InjectedCrash(BaseException): pass


class Journal:
    def __init__(self, path, binding, budget, crash_after=None, crash_pending=None):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.path=Path(path)
        self.checkpoint_dir = self.path.with_suffix(".checkpoints")
        self.checkpoint_dir.mkdir(parents=True, exist_ok=True)
        checkpoints = sorted(self.checkpoint_dir.glob("*.json"))
        self.checkpoint_sequence = int(checkpoints[-1].stem) if checkpoints else 0
        # Keep SQLite transactions in memory and publish a closed database image
        # after each reservation/commit. Atomic replacement avoids stale rollback
        # sidecars on filesystems that snapshot or synchronize live files.
        self.db = sqlite3.connect(":memory:")
        if checkpoints:
            saved = json.loads(checkpoints[-1].read_text(encoding="utf-8"))
            if digest(saved["database"]) != saved["hash"]:
                raise ValueError("checkpoint_hash_mismatch")
            self.db.deserialize(base64.b64decode(saved["database"], validate=True))
        elif self.path.exists():
            self.db.deserialize(self.path.read_bytes())
        self.db.executescript('''
          PRAGMA journal_mode=MEMORY;
          PRAGMA synchronous=FULL;
          CREATE TABLE IF NOT EXISTS run (id INTEGER PRIMARY KEY, binding TEXT, budget INTEGER, spent INTEGER, reserved INTEGER, status TEXT);
          CREATE TABLE IF NOT EXISTS actions (seq INTEGER PRIMARY KEY, action_id TEXT UNIQUE, kind TEXT, args TEXT, units INTEGER, status TEXT, result TEXT, seconds REAL);
          CREATE TABLE IF NOT EXISTS versions (version_id TEXT PRIMARY KEY, logical_id TEXT, payload TEXT);
          CREATE TABLE IF NOT EXISTS edges (parent TEXT, child TEXT, action_id TEXT, PRIMARY KEY(parent,child));
          CREATE TABLE IF NOT EXISTS certificates (logical_id TEXT PRIMARY KEY, payload TEXT);
          CREATE TABLE IF NOT EXISTS model_requests (action_id TEXT PRIMARY KEY, payload TEXT);
        ''')
        existing = self.db.execute("SELECT binding,budget FROM run WHERE id=1").fetchone()
        if existing and existing != (digest(binding), budget): raise ValueError("resume_binding_mismatch")
        with self.db:
            self.db.execute("INSERT OR IGNORE INTO run VALUES(1,?,?,0,0,'running')", (digest(binding), budget))
        self._persist()
        self.cursor = 0
        self.crash_after, self.crash_pending = crash_after, crash_pending

    def atomic(self, kind, args, units=0, callback=None):
        self.cursor += 1
        seq = self.cursor
        aid = digest([seq, kind, args])
        row = self.db.execute("SELECT action_id,status,result,units FROM actions WHERE seq=?", (seq,)).fetchone()
        if row:
            if row[0] != aid or row[3] not in (units, 0): raise ValueError("journal_divergence")
            if row[1] == "committed": return json.loads(row[2])
            if row[1] == "denied": raise BudgetExhausted()
            # A prior process could have sent a network request. Never resend it.
            if kind == "MODEL_REQUEST":
                result = {"outcome": "UNKNOWN", "reason": "uncertain", "sent": True, "usage": None}
                self._commit(seq, units, result, 0, kind, aid)
                return result
        else:
            denied = False
            with self.db:
                budget, spent, reserved = self.db.execute("SELECT budget,spent,reserved FROM run").fetchone()
                if budget is not None and spent + reserved + units > budget:
                    self.db.execute("INSERT INTO actions VALUES(?,?,?,?,?,'denied',?,0)", (seq, aid, kind, canonical(args), 0, canonical({"reason":"budget_exhausted", "required_units":units})))
                    denied = True
                else:
                    self.db.execute("INSERT INTO actions VALUES(?,?,?,?,?,'pending',NULL,0)", (seq, aid, kind, canonical(args), units))
                    self.db.execute("UPDATE run SET reserved=reserved+?", (units,))
            self._persist()
            if denied: raise BudgetExhausted()
        if self.crash_pending == seq: raise InjectedCrash()
        start = time.perf_counter()
        result = callback() if callback else args
        self._commit(seq, units, result, time.perf_counter()-start, kind, aid)
        if self.crash_after == seq: raise InjectedCrash()
        return result

    def _commit(self, seq, units, result, seconds, kind, aid):
        with self.db:
            self.db.execute("UPDATE actions SET status='committed',result=?,seconds=? WHERE seq=?", (canonical(result), seconds, seq))
            self.db.execute("UPDATE run SET reserved=reserved-?,spent=spent+?", (units, units))
            if kind == "STATE":
                for m in result["records"]:
                    self.db.execute("INSERT OR REPLACE INTO versions VALUES(?,?,?)", (m["version_id"], m["logical_id"], canonical(m)))
                if result.get("certificate"):
                    self.db.execute("INSERT OR REPLACE INTO certificates VALUES(?,?)", (result["logical_id"], canonical(result["certificate"])))
            if kind == "EDGE":
                self.db.execute("INSERT OR REPLACE INTO edges VALUES(?,?,?)", (result["parent"],result["child"],result["read_action_id"]))
            if kind == "INITIAL_GRAPH":
                self.db.executemany("INSERT OR IGNORE INTO edges VALUES(?,?,?)",[(a,b,"initial_observed") for a,b in result["edges"]])
            if kind == "MODEL_REQUEST":
                self.db.execute("INSERT OR REPLACE INTO model_requests VALUES(?,?)", (aid, canonical(result)))
        self._persist()

    def _persist(self):
        """Text checkpoint is authoritative while running; SQLite is an export."""
        encoded = base64.b64encode(self.db.serialize()).decode("ascii")
        body = canonical({"format":"sqlite-image-1","database":encoded,"hash":digest(encoded)}).encode("utf-8")
        self.checkpoint_sequence += 1
        self.checkpoint_path = self.checkpoint_dir/(f"{self.checkpoint_sequence:012d}.json")
        self._atomic_write(self.checkpoint_path, body)
        # Immutable generations cannot be replaced later by an older image.
        # Keep the latest two; interrupted cleanup does not affect selection.
        for old in sorted(self.checkpoint_dir.glob("*.json"))[:-2]:
            old.unlink()

    @staticmethod
    def _atomic_write(path, body):
        temporary = path.with_suffix(path.suffix+".tmp")
        with temporary.open("wb") as stream:
            stream.write(body)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        if os.name == "posix":
            directory = os.open(path.parent, os.O_RDONLY)
            try: os.fsync(directory)
            finally: os.close(directory)

    def actions(self):
        keys = ["seq","action_id","kind","args","units","status","result","seconds"]
        rows = []
        for row in self.db.execute("SELECT * FROM actions ORDER BY seq"):
            d = dict(zip(keys, row))
            d["args"] = json.loads(d["args"])
            d["result"] = json.loads(d["result"]) if d["result"] else None
            rows.append(d)
        return rows

    def ledger(self):
        budget, spent, reserved = self.db.execute("SELECT budget,spent,reserved FROM run").fetchone()
        d = dict(planned_budget=budget, spent_units=spent, reserved_units=reserved,
                 capsule_requests=0, capsule_reads=0, source_requests=0, source_reads=0,
                 bytes_read=0, rule_evaluations=0, leaf_extractions=0, cache_hits=0,
                 candidate_records_scored=0, graph_visits=0, audit_started=0, audit_completed=0,
                 audit_unknown=0, model_requests=0, model_request_intents=0, retry_requests=0, input_tokens=0, output_tokens=0,
                 tokens_status="actual_no_model_calls", candidate_seconds=0., evidence_seconds=0.,
                 root_operations=0, state_changes=0, root_seconds=0., graph_seconds=0.)
        for a in self.actions():
            k, r = a["kind"], a["result"] or {}
            if k in {"READ_CAPSULE","READ_SOURCE"}:
                prefix = "capsule" if k == "READ_CAPSULE" else "source"
                d[prefix+"_requests"] += 1
                if a["status"] == "committed":
                    d[prefix+"_reads"] += int(not r.get("reason"))
                    d["bytes_read"] += r.get("bytes",0)
                d["evidence_seconds"] += a["seconds"]
            if k == "CACHE_HIT":
                d["cache_hits"] += 1
                if r.get("resource") in {"capsule", "source"}: d[r["resource"]+"_requests"] += 1
            if a["status"] != "committed": continue
            if k == "RULE": d["rule_evaluations"] += 1
            if k == "EXTRACT": d["leaf_extractions"] += 1
            if k == "SELECT":
                d["candidate_records_scored"] += r.get("records",0)
                d["candidate_seconds"] += a["seconds"]
            if k == "GRAPH":
                d["graph_visits"] += r.get("visits",0)
                d["graph_seconds"] += a["seconds"]
            if k == "AUDIT_START": d["audit_started"] += 1
            if k == "AUDIT_END": d["audit_unknown" if r["outcome"] == "UNKNOWN" else "audit_completed"] += 1
            if k == "STATE":
                d["state_changes"] += int(r.get("reason")!="initial_snapshot")
                if r.get("reason") == "trusted_correction":
                    d["root_operations"] += 1; d["root_seconds"] += a["seconds"]
            if k == "MODEL_REQUEST":
                d["model_request_intents"] += 1
                if not r.get("sent",False): continue
                d["model_requests"] += 1
                d["retry_requests"] += int(a["args"].get("attempt",0)>0)
                usage = r.get("usage")
                if not usage or "prompt_tokens" not in usage or "completion_tokens" not in usage:
                    d["input_tokens"] = d["output_tokens"] = None; d["tokens_status"] = "unknown"
                elif d["tokens_status"] != "unknown":
                    d["input_tokens"] += usage["prompt_tokens"]; d["output_tokens"] += usage["completion_tokens"]
                    d["tokens_status"] = "reported"
        return d

    def finish(self, status):
        with self.db: self.db.execute("UPDATE run SET status=?", (status,))
        self._persist()
        # Reopen for a disk-backed integrity check, rather than trusting cached pages.
        checker=sqlite3.connect(":memory:")
        try:
            saved = json.loads(self.checkpoint_path.read_text(encoding="utf-8"))
            if digest(saved["database"]) != saved["hash"]: raise ValueError("checkpoint_hash_mismatch")
            checker.deserialize(base64.b64decode(saved["database"], validate=True))
            if checker.execute("PRAGMA integrity_check").fetchone()[0]!="ok":
                raise ValueError("database_integrity_check_failed")
        finally: checker.close()

    def close(self):
        # Last publication happens after all result/ledger reads, with no file
        # connection held by SQLite itself.
        self._persist()
        self._atomic_write(self.path, self.db.serialize())
        self.db.close()
