"""Only gateway reads environment content. Repair never receives its directory."""
import hashlib
import math
from pathlib import Path
from ..common import read_json


class EvidenceGateway:
    def __init__(self, directory, snapshot_id, journal):
        self.__directory = Path(directory)
        self.__index = read_json(self.__directory / "index.json")
        if self.__index["snapshot_id"] != snapshot_id: raise ValueError("snapshot_mismatch")
        self.snapshot_id, self.journal = snapshot_id, journal
        self.__cache = {}

    def _read(self, resource, key):
        ck = (self.snapshot_id, resource, key)
        if ck in self.__cache:
            self.journal.atomic("CACHE_HIT", {"resource":resource,"key":key,"snapshot_id":self.snapshot_id})
            return self.__cache[ck]
        meta = self.__index[resource].get(key)
        path = self.__directory / meta["path"] if meta else None
        exists = path is not None and path.is_file()
        actual_size = path.stat().st_size if exists else 0  # stat exposes no body
        units = max(1, math.ceil(actual_size/2048)) if exists else 1
        def read_paid():
            if not exists: return {"reason":"missing_"+resource,"bytes":0}
            if actual_size != meta["bytes"] or actual_size > 65536: return {"reason":"invalid_length","bytes":0}
            try: body = path.read_bytes()
            except OSError: return {"reason":"read_error","bytes":0}
            if len(body) != actual_size or hashlib.sha256(body).hexdigest() != meta["sha256"]:
                return {"reason":"evidence_integrity","bytes":len(body)}
            try: text=body.decode("utf-8")
            except UnicodeError: return {"reason":"invalid_encoding","bytes":len(body)}
            return {"text":text,"bytes":len(body)}
        result = self.journal.atomic("READ_"+resource.upper(), {"key":key,"snapshot_id":self.snapshot_id}, units, read_paid)
        result = dict(result, read_action_id=self.journal.actions()[self.journal.cursor-1]["action_id"])
        self.__cache[ck] = result
        return result

    def read_capsule(self, capsule_id): return self._read("capsule",capsule_id)

    def read_source(self, source_id, source_version, field_key, snapshot_id):
        if snapshot_id != self.snapshot_id: raise ValueError("snapshot_mismatch")
        return self._read("source", source_id+":"+source_version)
