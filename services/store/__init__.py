"""Metadata database (SQLite) + object storage (filesystem), scoped by workspace at the data layer.

Every read and write of product data goes through `WorkspaceStore`, which is bound to one
workspace_id at construction and adds it to every query and object path. There is no API
on WorkspaceStore that accepts a workspace id from a caller.
"""
import json
import os
import sqlite3
import threading
from pathlib import Path

from packages.util import now_iso, new_id
from packages.validate import check

# kind -> schema name used to validate before save (None = internal record, no schema)
KINDS = {
    "product": "product", "source": "source", "claim": "claim", "ruling": "ruling", "conflict": "conflict",
    "decision": "decision", "brief": "brief", "run": "run", "audit": "audit-event", "content": "content-item",
    "style-profile": "style-profile", "positioning-pack": "positioning-pack", "kb-status": None,
    "content-type": "content-type", "eval": None, "correction": None,
}


def default_data_dir():
    return Path(os.environ.get("VCE_DATA_DIR") or Path.home() / ".vce" / "data")


class TenancyError(PermissionError):
    pass


class Store:
    def __init__(self, root=None):
        self.root = Path(root or default_data_dir())
        self.root.mkdir(parents=True, exist_ok=True)
        self.objects = self.root / "objects"
        self.objects.mkdir(exist_ok=True)
        self._lock = threading.RLock()
        self.db = sqlite3.connect(str(self.root / "meta.sqlite"), check_same_thread=False)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript("""
        CREATE TABLE IF NOT EXISTS workspaces(id TEXT PRIMARY KEY, data TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS users(id TEXT PRIMARY KEY, email TEXT UNIQUE NOT NULL, name TEXT, pw TEXT NOT NULL, created_at TEXT);
        CREATE TABLE IF NOT EXISTS members(workspace_id TEXT, user_id TEXT, roles TEXT, PRIMARY KEY(workspace_id, user_id));
        CREATE TABLE IF NOT EXISTS sessions(token TEXT PRIMARY KEY, user_id TEXT, workspace_id TEXT, created_at TEXT);
        CREATE TABLE IF NOT EXISTS docs(workspace_id TEXT NOT NULL, kind TEXT NOT NULL, id TEXT NOT NULL,
            product_id TEXT, data TEXT NOT NULL, updated_at TEXT, PRIMARY KEY(workspace_id, kind, id));
        CREATE INDEX IF NOT EXISTS docs_by_product ON docs(workspace_id, kind, product_id);
        """)
        self.db.commit()

    # ----- global (non-product) records -----
    def create_workspace(self, name, ws_id=None, settings=None):
        ws = {"id": ws_id or new_id("ws"), "name": name, "created_at": now_iso(),
              "settings": {"retention_days": None, "run_budget_tokens": 3_000_000,
                           "workspace_budget_tokens": 50_000_000, "evidence_enabled": False, **(settings or {})}}
        check("workspace", ws)
        with self._lock:
            self.db.execute("INSERT INTO workspaces VALUES(?,?)", (ws["id"], json.dumps(ws)))
            self.db.commit()
        return ws

    def get_workspace(self, ws_id):
        rows = self.sql("SELECT data FROM workspaces WHERE id=?", (ws_id,))
        return json.loads(rows[0][0]) if rows else None

    def update_workspace(self, ws):
        check("workspace", ws)
        with self._lock:
            self.db.execute("UPDATE workspaces SET data=? WHERE id=?", (json.dumps(ws), ws["id"]))
            self.db.commit()

    def list_workspaces(self):
        return [json.loads(r[0]) for r in self.sql("SELECT data FROM workspaces ORDER BY id")]

    def sql(self, query, args=(), commit=False):
        with self._lock:
            cur = self.db.execute(query, args)
            rows = cur.fetchall()
            if commit:
                self.db.commit()
            return rows

    def workspace(self, ws_id):
        if not self.get_workspace(ws_id):
            raise TenancyError(f"unknown workspace {ws_id}")
        return WorkspaceStore(self, ws_id)


class WorkspaceStore:
    """All product data access for exactly one workspace."""

    def __init__(self, store, ws_id):
        self._s = store
        self.workspace_id = ws_id
        self._obj_root = (store.objects / ws_id).resolve()

    @property
    def settings(self):
        return self._s.get_workspace(self.workspace_id)["settings"]

    # ----- documents -----
    def put(self, kind, obj, id=None, product_id=None, **ctx):
        if kind not in KINDS:
            raise ValueError(f"unknown kind {kind}")
        if KINDS[kind]:
            check(KINDS[kind], obj, **ctx)
        if isinstance(obj, dict) and obj.get("workspace_id") not in (None, self.workspace_id):
            raise TenancyError("object belongs to another workspace")
        doc_id = id or obj.get("id")
        pid = product_id or (obj.get("product_id") if isinstance(obj, dict) else None)
        with self._s._lock:
            self._s.db.execute("INSERT OR REPLACE INTO docs VALUES(?,?,?,?,?,?)",
                               (self.workspace_id, kind, doc_id, pid, json.dumps(obj, ensure_ascii=False), now_iso()))
            self._s.db.commit()
        return obj

    def put_many(self, kind, objs, product_id=None, **ctx):
        rows = []
        for o in objs:
            if KINDS[kind]:
                check(KINDS[kind], o, **ctx)
            rows.append((self.workspace_id, kind, o["id"], product_id or o.get("product_id"),
                         json.dumps(o, ensure_ascii=False), now_iso()))
        with self._s._lock:
            self._s.db.executemany("INSERT OR REPLACE INTO docs VALUES(?,?,?,?,?,?)", rows)
            self._s.db.commit()

    def get(self, kind, id):
        rows = self._s.sql("SELECT data FROM docs WHERE workspace_id=? AND kind=? AND id=?", (self.workspace_id, kind, id))
        return json.loads(rows[0][0]) if rows else None

    def list(self, kind, product_id=None):
        if product_id is None:
            rows = self._s.sql("SELECT data FROM docs WHERE workspace_id=? AND kind=? ORDER BY id", (self.workspace_id, kind))
        else:
            rows = self._s.sql("SELECT data FROM docs WHERE workspace_id=? AND kind=? AND product_id=? ORDER BY id",
                               (self.workspace_id, kind, product_id))
        return [json.loads(r[0]) for r in rows]

    def delete(self, kind, id):
        """Only for internal, regenerable records. Claims, rulings, sources and audit are never deleted."""
        if kind in ("claim", "ruling", "audit", "source", "decision", "content"):
            raise PermissionError(f"{kind} records are never deleted")
        with self._s._lock:
            self._s.db.execute("DELETE FROM docs WHERE workspace_id=? AND kind=? AND id=?", (self.workspace_id, kind, id))
            self._s.db.commit()

    # ----- products -----
    def product(self, product_id):
        p = self.get("product", product_id)
        if not p:
            raise KeyError(f"no product {product_id} in this workspace")
        return p

    def claims(self, product_id):
        return {c["id"]: c for c in self.list("claim", product_id)}

    # ----- objects -----
    def _path(self, product_id, rel):
        p = (self._obj_root / product_id / rel).resolve()
        if not str(p).startswith(str(self._obj_root) + os.sep):
            raise TenancyError("object path escapes the workspace")
        return p

    def put_object(self, product_id, rel, data):
        p = self._path(product_id, rel)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data if isinstance(data, bytes) else data.encode("utf-8"))
        return f"{product_id}/{rel}"

    def put_json(self, product_id, rel, obj, schema=None, **ctx):
        if schema:
            check(schema, obj, **ctx)
        return self.put_object(product_id, rel, json.dumps(obj, indent=2, ensure_ascii=False))

    def get_object(self, ref):
        product_id, _, rel = ref.partition("/")
        return self._path(product_id, rel).read_bytes()

    def get_text(self, ref):
        return self.get_object(ref).decode("utf-8")

    def get_json(self, ref):
        return json.loads(self.get_object(ref))

    def has_object(self, ref):
        product_id, _, rel = ref.partition("/")
        return self._path(product_id, rel).exists()

    # ----- audit -----
    def audit(self, actor, action, target, reason=""):
        ev = {"id": new_id("ev"), "workspace_id": self.workspace_id, "actor": actor, "action": action,
              "target": target, "reason": reason, "created_at": now_iso()}
        return self.put("audit", ev)
