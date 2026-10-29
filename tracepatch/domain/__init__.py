"""Typed finite rules and bitemporal boundary behavior."""
from copy import deepcopy
from ..common import digest

UNKNOWN = None  # None is never a legal claim value.
TYPES = {"int": int, "bool": bool, "string": str}


def value_type(value):
    for name, cls in TYPES.items():
        if type(value) is cls:
            if cls is str and len(value) > 4096:
                raise ValueError("oversized_value")
            return name
    raise ValueError("invalid_type")


def validate_record(m):
    required = {"logical_id", "version_id", "kind", "owner_id", "scope_id", "claim_key", "value", "text", "entities", "created_step", "valid_from", "valid_to", "status", "capsule_id", "capsule_size_hint", "last_used_step", "use_count"}
    if set(m) - required - {"reason", "certificate"} or not required <= m.keys():
        raise ValueError("public_schema_violation")
    value_type(m["value"])
    if m["status"] not in {"ACTIVE", "QUARANTINED", "SUPERSEDED"} or m["kind"] not in {"fact", "derived", "cache"}:
        raise ValueError("invalid_record")
    if len(m["text"]) > 16384 or len(m["entities"]) > 64:
        raise ValueError("oversized_record")
    if m["valid_to"] is not None and m["valid_to"] <= m["valid_from"]:
        raise ValueError("invalid_interval")


def execute(op, values):
    arity = {"COPY": (1, 1), "EQ": (2, 2), "GE": (2, 2), "LE": (2, 2), "AND": (1, 4), "OR": (1, 4), "NOT": (1, 1)}
    if op not in arity or not arity[op][0] <= len(values) <= arity[op][1]:
        raise ValueError("invalid_operation")
    for x in values:
        if x is not None:
            value_type(x)
    if op in {"AND", "OR", "NOT"} and any(x is not None and type(x) is not bool for x in values):
        raise ValueError("invalid_type")
    if op in {"GE", "LE"} and any(x is not None and type(x) is not int for x in values):
        raise ValueError("invalid_type")
    if op == "EQ" and all(x is not None for x in values) and type(values[0]) is not type(values[1]):
        raise ValueError("invalid_type")
    if op == "AND":
        return False if any(x is False for x in values) else (True if all(x is True for x in values) else None)
    if op == "OR":
        return True if any(x is True for x in values) else (False if all(x is False for x in values) else None)
    if any(x is None for x in values):
        return None
    if op == "COPY": return values[0]
    if op == "NOT": return not values[0]
    if op == "EQ": return values[0] == values[1]
    if op == "GE": return values[0] >= values[1]
    if op == "LE": return values[0] <= values[1]


def compatible(m, event):
    end = lambda v: float("inf") if v is None else v
    return (m["owner_id"] == event["owner_id"] and m["scope_id"] == event["scope_id"]
            and max(m["valid_from"], event["effective_from"]) < min(end(m["valid_to"]), end(event["effective_to"])))


class TemporalStore:
    """Boundary API: half-open intervals, successor segments, no physical delete."""
    def __init__(self, records):
        self.records = deepcopy(records)
        self.events = set()

    def apply(self, event):
        if event["event_id"] in self.events: return
        value_type(event["new_value"])
        targets = [m for m in self.records if m["logical_id"] == event["target_logical_id"] and m["status"] == "ACTIVE" and m["owner_id"] == event["owner_id"]]
        if event["kind"] == "CONTEXTUAL_ASSERTION":
            base = next(m for m in targets if m["version_id"] == event["target_version_id"])
            if any(m["scope_id"] == event["scope_id"] and compatible(m, event) for m in targets):
                raise ValueError("context_overlap")
            new = dict(base, scope_id=event["scope_id"], value=event["new_value"], valid_from=event["effective_from"], valid_to=event["effective_to"], version_id=digest(event)[:24])
            self.records.append(new)
        elif event["kind"] in {"UPDATE", "CORRECTION"}:
            targets = [m for m in targets if compatible(m, event)]
            if not any(m["version_id"] == event["target_version_id"] for m in targets):
                raise ValueError("stale_target")
            for m in targets:
                lo, hi = max(m["valid_from"], event["effective_from"]), event["effective_to"]
                if m["valid_to"] is not None: hi = min(m["valid_to"], hi) if hi is not None else m["valid_to"]
                old = deepcopy(m)
                m["status"] = "SUPERSEDED"
                segments = [(lo, hi, event["new_value"])]
                if old["valid_from"] < lo: segments.append((old["valid_from"], lo, old["value"]))
                if hi is not None and (old["valid_to"] is None or hi < old["valid_to"]): segments.append((hi, old["valid_to"], old["value"]))
                for a, b, v in segments:
                    self.records.append(dict(old, valid_from=a, valid_to=b, value=v, version_id=digest([event, a, b])[:24]))
        else: raise ValueError("invalid_event")
        self.events.add(event["event_id"])


class QueryReader:
    def __init__(self, records): self.records = records

    def query(self, logical_id, owner_id, scope_id, at, claim_key=None):
        matches = [m for m in self.records if m["logical_id"] == logical_id and m["owner_id"] == owner_id and m["scope_id"] == scope_id and m["status"] == "ACTIVE" and m["valid_from"] <= at and (m["valid_to"] is None or at < m["valid_to"]) and (claim_key is None or m["claim_key"] == claim_key)]
        if len(matches) > 1: raise ValueError("overlapping_active_versions")
        return {"outcome": "ANSWER", "value": matches[0]["value"], "version_id": matches[0]["version_id"]} if matches else {"outcome": "ABSTAIN", "value": None}
