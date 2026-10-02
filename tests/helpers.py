import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ["VCE_PROVIDER"] = "offline"
os.environ["VCE_ALLOW_PLAINTEXT_EVIDENCE"] = "1"

from services.store import Store  # noqa: E402

ADMIN = {"email": "admin@example.test", "roles": ["admin", "editor", "reviewer", "sme", "compliance"]}
EDITOR = {"email": "editor@example.test", "roles": ["editor"]}


class StoreCase(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="vce-test-")
        self.store = Store(self.dir)
        self.store.create_workspace("A", "ws-a", {"evidence_enabled": True})
        self.store.create_workspace("B", "ws-b")
        self.ws = self.store.workspace("ws-a")
        self.wsb = self.store.workspace("ws-b")

    def tearDown(self):
        self.store.db.close()
        shutil.rmtree(self.dir, ignore_errors=True)

    def load(self, slug="lumen", ingest=True):
        from services import fixtures, orchestrator
        fixtures.load(self.ws, ADMIN, slug)
        if ingest:
            orchestrator.ingest_product(self.ws, slug)
        return self.ws.product(slug)


def claim(cid, text="Acme Box stores data for 30 days.", status="verified", category="capability", confidence="high",
          source_id="tru-doc", quote=None, product_id="p"):
    from packages.util import quote_hash
    q = quote or text
    return {"id": cid, "product_id": product_id, "text": text, "quote": q, "quote_hash": quote_hash(q), "source_id": source_id,
            "location": "Doc ¶1", "category": category, "confidence": confidence, "status": status, "user_decision": None,
            "deprioritized": False, "status_reason": "", "count": None, "created_at": "2026-01-01T00:00:00Z",
            "updated_at": "2026-01-01T00:00:00Z"}
