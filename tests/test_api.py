import json
import threading
import time
import urllib.error
import urllib.request
from http.cookiejar import CookieJar
from http.server import ThreadingHTTPServer

from tests.helpers import ADMIN, StoreCase, unittest
from services import api


class Client:
    def __init__(self, base):
        self.base = base
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(CookieJar()))

    def call(self, method, path, body=None, csrf=True):
        data = json.dumps(body).encode() if body is not None else (b"{}" if method != "GET" else None)
        req = urllib.request.Request(self.base + path, data=data, method=method)
        req.add_header("Content-Type", "application/json")
        if csrf and method != "GET":
            req.add_header("X-Requested-With", "vce")
        try:
            with self.opener.open(req) as r:
                raw = r.read()
                return r.status, (json.loads(raw) if r.headers.get("Content-Type", "").startswith("application/json") else raw)
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read() or b"{}")

    def wait(self, job_id):
        for _ in range(200):
            code, j = self.call("GET", f"/api/jobs/{job_id}")
            if j["status"] != "running":
                return j
            time.sleep(0.05)
        raise AssertionError("job did not finish")


class ApiTests(StoreCase):
    def setUp(self):
        super().setUp()
        for ws_id, email, roles in (("ws-a", "admin@example.test", ADMIN["roles"]), ("ws-b", "b@example.test", ["admin"]),
                                    ("ws-a", "editor@example.test", ["editor"])):
            u = api.user_by_email(self.store, email)
            uid = u["id"] if u else api.create_user(self.store, email, "correct-horse-1")
            api.set_member(self.store, ws_id, uid, roles)
        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), api.make_handler(api.App(self.store)))
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.srv.server_address[1]}"

    def tearDown(self):
        self.srv.shutdown()
        self.srv.server_close()
        super().tearDown()

    def login(self, email):
        c = Client(self.base)
        code, _ = c.call("POST", "/api/login", {"email": email, "password": "correct-horse-1"})
        self.assertEqual(code, 200)
        return c

    def test_auth_required_and_wrong_password(self):
        c = Client(self.base)
        self.assertEqual(c.call("GET", "/api/products")[0], 401)
        self.assertEqual(c.call("POST", "/api/login", {"email": "admin@example.test", "password": "nope-nope-nope"})[0], 401)

    def test_mutations_need_csrf_header(self):
        c = self.login("admin@example.test")
        code, _ = c.call("POST", "/api/products", {"name": "Acme", "claim_prefix": "ACME"}, csrf=False)
        self.assertEqual(code, 403)

    def test_workspace_comes_from_session_not_request(self):
        a = self.login("admin@example.test")
        self.assertEqual(a.call("POST", "/api/products", {"name": "Acme Box", "claim_prefix": "ACME", "slug": "acme",
                                                          "workspace_id": "ws-b"})[0], 200)
        b = self.login("b@example.test")
        self.assertEqual(b.call("GET", "/api/products")[1], [])
        self.assertEqual(b.call("GET", "/api/products/acme")[0], 404)
        self.assertEqual(b.call("GET", "/api/products/acme/claims")[0], 200)  # empty for another workspace
        self.assertEqual(b.call("GET", "/api/products/acme/claims")[1]["total"], 0)

    def test_roles_enforced(self):
        e = self.login("editor@example.test")
        code, body = e.call("POST", "/api/products", {"name": "Acme", "claim_prefix": "ACME"})
        self.assertEqual(code, 403)
        self.assertIn("admin", body["error"])

    def test_full_flow_through_api(self):
        self.load("lumen", ingest=False)
        a = self.login("admin@example.test")
        code, est = a.call("GET", "/api/products/lumen/estimate?kind=ingest")
        self.assertGreater(est["tokens"], 0)
        job = a.wait(a.call("POST", "/api/products/lumen/ingest")[1]["job_id"])
        self.assertEqual(job["status"], "done", job.get("error"))
        code, q = a.call("GET", "/api/products/lumen/review-queue")
        self.assertTrue(q)
        cid = q[0]["claims"][0]["id"]
        self.assertEqual(a.call("POST", f"/api/products/lumen/claims/{cid}/rule", {"kind": "doc-wrong"})[0], 400)  # note required
        code, c = a.call("POST", f"/api/products/lumen/claims/{cid}/rule", {"kind": "confirmed", "note": "Checked against spec"})
        self.assertEqual(c["status"], "verified")
        code, b = a.call("POST", "/api/products/lumen/briefs", {"content_type": "email", "title": "Comfort complaints",
                                                                "audience": "Facilities directors", "goal": "Book a call",
                                                                "stage": "problem-aware"})
        self.assertEqual(code, 200, b)
        job = a.wait(a.call("POST", f"/api/briefs/{b['id']}/run")[1]["job_id"])
        self.assertEqual(job["status"], "done", job.get("error"))
        code, item = a.call("GET", f"/api/content/{b['id']}")
        self.assertTrue(item["rounds"][0]["verdicts"])
        status = item["item"]["status"]
        if status not in ("approved", "approved-override"):
            self.assertEqual(a.call("GET", f"/api/content/{b['id']}/export?fmt=md")[0], 400)
            self.assertEqual(a.call("POST", f"/api/content/{b['id']}/override", {"reason": ""})[0], 400)
            code, rep = a.call("POST", f"/api/content/{b['id']}/override", {"reason": "Reviewed by legal"})
            self.assertEqual(rep["status"], "approved-override")
        code, data = a.call("GET", f"/api/content/{b['id']}/export?fmt=md")
        self.assertEqual(code, 200)
        self.assertNotIn(b"[[", data)
        code, cmp_ = a.call("GET", f"/api/content/{b['id']}/compare?a=1&b={len(item['rounds'])}")
        self.assertEqual(code, 200)
        self.assertEqual(a.call("GET", "/api/products/lumen/gaps")[0], 200)
        self.assertEqual(a.call("GET", "/api/quality")[0], 200)
        self.assertEqual(a.call("GET", "/api/cost")[0], 200)
        code, ev = a.call("GET", "/api/audit")
        self.assertIn("content.export", {e["action"] for e in ev})

    def test_static_index(self):
        req = urllib.request.urlopen(self.base + "/")
        self.assertEqual(req.status, 200)


if __name__ == "__main__":
    unittest.main()
