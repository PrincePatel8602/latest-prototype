"""In-memory stand-in for a Pinecone integrated-embedding index (tests only).
Scores = word overlap between query and record text; supports $eq/$gte/$lte/$and metadata filters."""
import re

_w = lambda s: set(re.findall(r"[a-z0-9]+", s.lower()))


def _ok(meta, flt):
    if not flt:
        return True
    if "$and" in flt:
        return all(_ok(meta, c) for c in flt["$and"])
    (k, cond), = flt.items()
    v = meta.get(k)
    for op, x in cond.items():
        if v is None or not {"$eq": lambda: v == x, "$gte": lambda: v >= x, "$lte": lambda: v <= x}[op]():
            return False
    return True


class FakeIndex:
    def __init__(self):
        self.records, self.upsert_calls = {}, 0

    def upsert_records(self, *, namespace, records):   # keyword-only, like the real SDK
        assert len(records) <= 96
        self.upsert_calls += 1
        for r in records:
            self.records[(namespace, r["_id"])] = dict(r)

    def search(self, *, namespace, top_k=None, inputs=None, filter=None, fields=None):
        text, flt = inputs["text"], filter
        hits = []
        for (ns, rid), r in self.records.items():
            meta = {k: v for k, v in r.items() if k not in ("_id", "chunk_text")}
            if ns == namespace and _ok(meta, flt):
                score = len(_w(text) & _w(r["chunk_text"])) / max(1, len(_w(text)))
                hits.append({"_id": rid, "_score": score, "fields": meta})
        hits.sort(key=lambda h: -h["_score"])
        return {"result": {"hits": hits[:top_k]}}

    def describe_index_stats(self):
        return {"namespaces": {}}
