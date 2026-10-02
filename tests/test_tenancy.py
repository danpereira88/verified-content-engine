from tests.helpers import ADMIN, StoreCase, unittest
from services import actions
from services.store import TenancyError


class TenancyTests(StoreCase):
    def test_documents_are_scoped_to_their_workspace(self):
        actions.create_product(self.ws, ADMIN, "Acme Box", "ACME", slug="acme")
        self.assertIsNotNone(self.ws.get("product", "acme"))
        self.assertIsNone(self.wsb.get("product", "acme"))
        self.assertEqual(self.wsb.list("product"), [])

    def test_same_ids_in_two_workspaces_do_not_collide(self):
        actions.create_product(self.ws, ADMIN, "Acme Box", "ACME", slug="acme")
        actions.create_product(self.wsb, ADMIN, "Other", "OTH", slug="acme")
        self.assertEqual(self.ws.product("acme")["name"], "Acme Box")
        self.assertEqual(self.wsb.product("acme")["name"], "Other")

    def test_objects_are_scoped_and_paths_cannot_escape(self):
        ref = self.ws.put_object("acme", "x/file.txt", "secret")
        self.assertEqual(self.ws.get_text(ref), "secret")
        with self.assertRaises(FileNotFoundError):
            self.wsb.get_text(ref)
        with self.assertRaises(TenancyError):
            self.ws.put_object("acme", "../../ws-b/acme/evil.txt", "x")
        with self.assertRaises(TenancyError):
            self.ws.get_object("../ws-b/acme/x")

    def test_cannot_write_object_claiming_another_workspace(self):
        p = actions.create_product(self.ws, ADMIN, "Acme Box", "ACME", slug="acme")
        with self.assertRaises(TenancyError):
            self.wsb.put("product", dict(p))

    def test_unknown_workspace(self):
        with self.assertRaises(TenancyError):
            self.store.workspace("ws-nope")

    def test_human_records_are_never_deleted(self):
        for kind in ("claim", "ruling", "audit", "source", "decision", "content"):
            with self.assertRaises(PermissionError):
                self.ws.delete(kind, "x")

    def test_claims_and_runs_scoped(self):
        self.load("lumen")
        self.assertTrue(self.ws.claims("lumen"))
        self.assertEqual(self.wsb.claims("lumen"), {})
        self.assertEqual(self.wsb.list("run"), [])


if __name__ == "__main__":
    unittest.main()
