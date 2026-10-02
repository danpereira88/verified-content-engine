"""HTTP API (stdlib). Authentication, roles, workspace scoping, human actions, background jobs.

- The workspace comes from the authenticated session, never from the request.
- Human actions (rulings, overrides, approvals, exports) only happen here, on behalf of a signed-in person.
- Binds to 127.0.0.1 by default (local mode). Put a TLS-terminating proxy in front for hosted use.
"""
import base64
import difflib
import hashlib
import hmac
import json
import mimetypes
import os
import re
import secrets
import threading
import traceback
import urllib.parse
from http import cookies
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from packages import gate, registry
from packages.util import now_iso, new_id, strip_tags
from services import actions, ingest, orchestrator
from services.store import Store, TenancyError

WEB = Path(__file__).resolve().parent.parent.parent / "apps" / "web"
SESSION_COOKIE = "vce_session"


# ---------------- users & sessions ----------------

def hash_pw(pw, salt=None):
    salt = salt or secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac("sha256", pw.encode(), salt.encode(), 200_000)
    return f"pbkdf2${salt}${dk.hex()}"


def check_pw(pw, stored):
    try:
        _, salt, _ = stored.split("$")
    except ValueError:
        return False
    return hmac.compare_digest(hash_pw(pw, salt), stored)


def create_user(store, email, password, name=""):
    if len(password) < 10:
        raise ValueError("password must be at least 10 characters")
    uid = new_id("usr")
    store.sql("INSERT INTO users VALUES(?,?,?,?,?)", (uid, email.lower(), name, hash_pw(password), now_iso()), commit=True)
    return uid


def set_member(store, ws_id, user_id, roles):
    bad = set(roles) - {"editor", "reviewer", "sme", "compliance", "admin"}
    if bad:
        raise ValueError(f"unknown roles {sorted(bad)}")
    store.sql("INSERT OR REPLACE INTO members VALUES(?,?,?)", (ws_id, user_id, json.dumps(sorted(roles))), commit=True)


def user_by_email(store, email):
    rows = store.sql("SELECT id, email, name, pw FROM users WHERE email=?", (email.lower(),))
    return dict(zip(("id", "email", "name", "pw"), rows[0])) if rows else None


def memberships(store, user_id):
    return [{"workspace_id": w, "roles": json.loads(r)} for w, r in
            store.sql("SELECT workspace_id, roles FROM members WHERE user_id=?", (user_id,))]


# ---------------- background jobs ----------------

class Jobs:
    def __init__(self):
        self.lock, self.jobs = threading.Lock(), {}

    def start(self, ws_id, kind, fn):
        jid = new_id("job")
        with self.lock:
            self.jobs[jid] = {"id": jid, "workspace_id": ws_id, "kind": kind, "status": "running", "result": None,
                              "error": None, "started_at": now_iso(), "progress": []}

        def progress(run_id, step, status):
            with self.lock:
                j = self.jobs[jid]
                j["run_id"] = run_id
                j["progress"] = (j["progress"] + [{"step": step, "status": status, "at": now_iso()}])[-200:]

        def body():
            try:
                res = fn(progress)
                with self.lock:
                    self.jobs[jid].update(status="done", result=res)
            except Exception as e:  # surfaced to the UI with context
                with self.lock:
                    self.jobs[jid].update(status="failed", error=f"{type(e).__name__}: {e}")
                traceback.print_exc()
        threading.Thread(target=body, daemon=True).start()
        return jid

    def get(self, ws_id, jid):
        with self.lock:
            j = self.jobs.get(jid)
            return json.loads(json.dumps(j, default=str)) if j and j["workspace_id"] == ws_id else None


# ---------------- request handling ----------------

class HTTPError(Exception):
    def __init__(self, code, msg):
        self.code, self.msg = code, msg


ROUTES = []


def route(method, pattern):
    def deco(fn):
        ROUTES.append((method, re.compile("^" + pattern + "$"), fn))
        return fn
    return deco


class App:
    def __init__(self, store, provider=None):
        self.store, self.jobs, self.provider = store, Jobs(), provider

    def session(self, token):
        if not token:
            return None
        rows = self.store.sql("SELECT user_id, workspace_id FROM sessions WHERE token=?", (token,))
        if not rows:
            return None
        uid, ws_id = rows[0]
        u = self.store.sql("SELECT id, email, name FROM users WHERE id=?", (uid,))
        if not u:
            return None
        roles = next((m["roles"] for m in memberships(self.store, uid) if m["workspace_id"] == ws_id), [])
        return {"id": u[0][0], "email": u[0][1], "name": u[0][2], "workspace_id": ws_id, "roles": roles, "token": token}


class Ctx:
    def __init__(self, app, handler, user, body, query):
        self.app, self.h, self.user, self.body, self.query = app, handler, user, body, query
        self.ws = app.store.workspace(user["workspace_id"]) if user else None

    def need(self, *fields):
        missing = [f for f in fields if self.body.get(f) in (None, "")]
        if missing:
            raise HTTPError(400, f"missing {', '.join(missing)}")
        return [self.body[f] for f in fields]


def make_handler(app):
    class Handler(BaseHTTPRequestHandler):
        server_version = "VCE/1.0"

        def log_message(self, fmt, *args):  # no request bodies or source text in logs
            if os.environ.get("VCE_ACCESS_LOG"):
                super().log_message(fmt, *args)

        def _send(self, code, body, ctype="application/json", headers=None):
            data = body if isinstance(body, bytes) else json.dumps(body, ensure_ascii=False, default=str).encode()
            self.send_response(code)
            self.send_header("Content-Type", ctype + ("; charset=utf-8" if ctype.startswith(("text", "application/json")) else ""))
            self.send_header("Content-Length", str(len(data)))
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Security-Policy", "default-src 'self'; style-src 'self' 'unsafe-inline'")
            for k, v in (headers or {}).items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(data)

        def _token(self):
            c = cookies.SimpleCookie(self.headers.get("Cookie", ""))
            return c[SESSION_COOKIE].value if SESSION_COOKIE in c else None

        def _dispatch(self, method):
            parsed = urllib.parse.urlparse(self.path)
            path = parsed.path
            if method == "GET" and not path.startswith("/api/"):
                return self._static(path)
            query = {k: v[-1] for k, v in urllib.parse.parse_qs(parsed.query).items()}
            body = {}
            if method in ("POST", "PUT", "DELETE"):
                if self.headers.get("X-Requested-With") != "vce":
                    return self._send(403, {"error": "missing X-Requested-With header"})
                n = int(self.headers.get("Content-Length") or 0)
                if n > 60 * 1024 * 1024:
                    return self._send(413, {"error": "upload too large"})
                raw = self.rfile.read(n) if n else b""
                try:
                    body = json.loads(raw) if raw else {}
                except json.JSONDecodeError:
                    return self._send(400, {"error": "body must be JSON"})
            user = app.session(self._token())
            for m, rx, fn in ROUTES:
                mt = rx.match(path)
                if m == method and mt:
                    if not user and not getattr(fn, "public", False):
                        return self._send(401, {"error": "sign in required"})
                    try:
                        res = fn(Ctx(app, self, user, body, query), *mt.groups())
                    except HTTPError as e:
                        return self._send(e.code, {"error": e.msg})
                    except actions.Forbidden as e:
                        return self._send(403, {"error": str(e)})
                    except TenancyError as e:
                        return self._send(404, {"error": "not found"})
                    except (KeyError, FileNotFoundError) as e:
                        return self._send(404, {"error": f"not found: {e}"})
                    except (ValueError, ingest.IngestError) as e:
                        return self._send(400, {"error": str(e)})
                    except orchestrator.RunFailed as e:
                        return self._send(409, {"error": str(e)})
                    except Exception as e:
                        traceback.print_exc()
                        return self._send(500, {"error": f"{type(e).__name__}: {e}"})
                    if isinstance(res, tuple) and len(res) == 3 and isinstance(res[0], (bytes, dict, list)):
                        return self._send(200, res[0], res[1], res[2])
                    return self._send(200, res)
            return self._send(404, {"error": "no such route"})

        def _static(self, path):
            rel = path.lstrip("/") or "index.html"
            p = (WEB / rel).resolve()
            if not str(p).startswith(str(WEB.resolve())) or not p.is_file():
                p = WEB / "index.html"
            ctype = mimetypes.guess_type(str(p))[0] or "application/octet-stream"
            return self._send(200, p.read_bytes(), ctype)

        def do_GET(self):
            self._dispatch("GET")

        def do_POST(self):
            self._dispatch("POST")

        def do_PUT(self):
            self._dispatch("PUT")

        def do_DELETE(self):
            self._dispatch("DELETE")
    return Handler


def public(fn):
    fn.public = True
    return fn


def need_role(ctx, *roles):
    if not set(ctx.user["roles"]) & set(roles):
        raise actions.Forbidden(f"needs one of {sorted(roles)}")


# ---------------- routes: auth & workspace ----------------

@route("POST", "/api/login")
@public
def login(ctx):
    email, pw = ctx.need("email", "password")
    u = user_by_email(ctx.app.store, email)
    if not u or not check_pw(pw, u["pw"]):
        raise HTTPError(401, "wrong email or password")
    ms = memberships(ctx.app.store, u["id"])
    if not ms:
        raise HTTPError(403, "you're not a member of any workspace")
    ws_id = ctx.body.get("workspace_id") or ms[0]["workspace_id"]
    if ws_id not in {m["workspace_id"] for m in ms}:
        raise HTTPError(403, "not a member of that workspace")
    token = secrets.token_urlsafe(32)
    ctx.app.store.sql("INSERT INTO sessions VALUES(?,?,?,?)", (token, u["id"], ws_id, now_iso()), commit=True)
    cookie = f"{SESSION_COOKIE}={token}; HttpOnly; SameSite=Strict; Path=/"
    return {"ok": True}, "application/json", {"Set-Cookie": cookie}


@route("POST", "/api/logout")
def logout(ctx):
    ctx.app.store.sql("DELETE FROM sessions WHERE token=?", (ctx.user["token"],), commit=True)
    return {"ok": True}, "application/json", {"Set-Cookie": f"{SESSION_COOKIE}=; Max-Age=0; Path=/"}


@route("GET", "/api/me")
def me(ctx):
    ws = ctx.app.store.get_workspace(ctx.user["workspace_id"])
    return {"user": {k: ctx.user[k] for k in ("email", "name", "roles")}, "workspace": {"id": ws["id"], "name": ws["name"]},
            "workspaces": memberships(ctx.app.store, ctx.user["id"]),
            "provider": os.environ.get("VCE_PROVIDER", "offline"), "data_dir": str(ctx.app.store.root)}


@route("GET", "/api/settings")
def get_settings(ctx):
    ws = ctx.app.store.get_workspace(ctx.user["workspace_id"])
    members = [{"email": e, "name": n, "roles": json.loads(r)} for e, n, r in ctx.app.store.sql(
        "SELECT u.email, u.name, m.roles FROM members m JOIN users u ON u.id=m.user_id WHERE m.workspace_id=?",
        (ws["id"],))]
    return {"workspace": ws, "members": members, "data_dir": str(ctx.app.store.root),
            "provider": os.environ.get("VCE_PROVIDER", "offline"),
            "evidence_encryption": "fernet" if ingest._fernet() else
            ("plaintext (fixtures only)" if os.environ.get("VCE_ALLOW_PLAINTEXT_EVIDENCE") == "1" else "unavailable")}


@route("PUT", "/api/settings")
def put_settings(ctx):
    actions.require(ctx.user, "settings.update")
    ws = ctx.app.store.get_workspace(ctx.user["workspace_id"])
    for k in ("retention_days", "run_budget_tokens", "workspace_budget_tokens", "evidence_enabled"):
        if k in ctx.body:
            ws["settings"][k] = ctx.body[k]
    if "name" in ctx.body:
        ws["name"] = ctx.body["name"]
    ctx.app.store.update_workspace(ws)
    ctx.ws.audit(ctx.user["email"], "settings.update", ws["id"], json.dumps(ctx.body)[:300])
    return ws


@route("POST", "/api/members")
def add_member(ctx):
    actions.require(ctx.user, "member.manage")
    email, roles = ctx.need("email", "roles")
    u = user_by_email(ctx.app.store, email)
    if not u:
        pw = ctx.body.get("password") or ""
        create_user(ctx.app.store, email, pw, ctx.body.get("name", ""))
        u = user_by_email(ctx.app.store, email)
    set_member(ctx.app.store, ctx.user["workspace_id"], u["id"], roles)
    ctx.ws.audit(ctx.user["email"], "member.set", email, ",".join(roles))
    return {"ok": True}


@route("GET", "/api/audit")
def audit(ctx):
    need_role(ctx, "admin", "reviewer", "compliance")
    evs = sorted(ctx.ws.list("audit"), key=lambda e: e["created_at"], reverse=True)
    if ctx.query.get("format") == "csv":
        lines = ["created_at,actor,action,target,reason"]
        for e in reversed(evs):
            lines.append(",".join('"' + str(e.get(k, "")).replace('"', '""') + '"' for k in ("created_at", "actor", "action", "target", "reason")))
        ctx.ws.audit(ctx.user["email"], "audit.export", ctx.ws.workspace_id)
        return ("\n".join(lines) + "\n").encode(), "text/csv", {"Content-Disposition": "attachment; filename=audit.csv"}
    return evs[: int(ctx.query.get("limit", 300))]


# ---------------- products & sources ----------------

def _product_view(ws, p):
    st = ws.get("kb-status", p["id"]) or orchestrator.refresh_status(ws, p["id"])
    srcs = ws.list("source", p["id"])
    checklist = [
        {"step": "Add truth sources (product docs)", "done": st["sources"]["truth"] > 0},
        {"step": "Add style examples", "done": st["sources"]["style"] > 0},
        {"step": "Add positioning material", "done": st["sources"]["positioning"] > 0},
        {"step": "Build the knowledge base", "done": bool(st.get("built_sha"))},
        {"step": "Review claims", "done": st["verified"] > 0 and st["needs_review"] == 0},
        {"step": "Accept the style threshold", "done": p.get("style_threshold") is not None},
    ]
    return dict(p, kb_status=st, checklist=checklist, source_count=len([s for s in srcs if s["status"] == "active"]))


@route("GET", "/api/products")
def list_products(ctx):
    return [_product_view(ctx.ws, p) for p in ctx.ws.list("product")]


@route("POST", "/api/products")
def new_product(ctx):
    name, prefix = ctx.need("name", "claim_prefix")
    return actions.create_product(ctx.ws, ctx.user, name, prefix.upper(), slug=ctx.body.get("slug"),
                                  company=ctx.body.get("company", ""), content_types=ctx.body.get("content_types"),
                                  high_risk_categories=ctx.body.get("high_risk_categories"),
                                  buyer_persona=ctx.body.get("buyer_persona"))


@route("GET", "/api/products/([\\w-]+)")
def get_product(ctx, pid):
    return _product_view(ctx.ws, ctx.ws.product(pid))


@route("PUT", "/api/products/([\\w-]+)")
def put_product(ctx, pid):
    return actions.update_product(ctx.ws, ctx.user, pid, **{k: ctx.body.get(k) for k in
                                  ("name", "company", "content_types", "high_risk_categories", "buyer_persona", "checkers", "models")})


@route("GET", "/api/products/([\\w-]+)/sources")
def list_sources(ctx, pid):
    ctx.ws.product(pid)
    return sorted(ctx.ws.list("source", pid), key=lambda s: (s["type"], s["id"]))


@route("POST", "/api/products/([\\w-]+)/sources")
def upload_source(ctx, pid):
    stype, name, content = ctx.need("type", "name", "content_base64")
    src, changed, stale = actions.add_source(ctx.ws, ctx.user, pid, stype, name, base64.b64decode(content))
    return {"source": src, "changed": changed, "staleness": stale}


@route("POST", "/api/products/([\\w-]+)/sources/import")
def import_site(ctx, pid):
    actions.require(ctx.user, "source.add")
    (base,) = ctx.need("base")
    mode, limit = ctx.body.get("mode", "llms"), int(ctx.body.get("limit", 300))
    ws, user = ctx.ws, ctx.user

    def job(progress):
        res = ingest.import_docs_site(ws, pid, base, mode, limit)
        ws.audit(user["email"], "source.import", base, f"{res['pages']} pages, {len(res['changed'])} changed")
        if res["changed"]:
            res["staleness"] = orchestrator.mark_stale(ws, pid, res["changed"])
        return res
    return {"job_id": ctx.app.jobs.start(ws.workspace_id, "import", job)}


@route("DELETE", "/api/products/([\\w-]+)/sources/([\\w-]+)")
def delete_source(ctx, pid, sid):
    src, stale = actions.remove_source(ctx.ws, ctx.user, pid, sid)
    return {"source": src, "staleness": stale}


@route("GET", "/api/products/([\\w-]+)/sources/([\\w-]+)")
def source_text(ctx, pid, sid):
    s = ctx.ws.get("source", sid)
    if not s or s["product_id"] != pid:
        raise KeyError(sid)
    if s["type"] == "evidence":
        need_role(ctx, "admin", "sme")
    return {"source": s, "blocks": ingest.normalized(ctx.ws, s)["blocks"]}


@route("GET", "/api/products/([\\w-]+)/estimate")
def estimate(ctx, pid):
    kind = ctx.query.get("kind", "content")
    return {"kind": kind, "tokens": orchestrator.estimate_tokens(ctx.ws, pid, kind),
            "provider": os.environ.get("VCE_PROVIDER", "offline")}


@route("POST", "/api/products/([\\w-]+)/ingest")
def run_ingest(ctx, pid):
    actions.require(ctx.user, "ingest")
    ws, user, provider = ctx.ws, ctx.user, ctx.app.provider
    ws.product(pid)

    def job(progress):
        res = orchestrator.ingest_product(ws, pid, provider=provider, progress=progress)
        ws.audit(user["email"], "ingest", pid, f"{res['claims']} claims")
        return res
    return {"job_id": ctx.app.jobs.start(ws.workspace_id, "ingest", job)}


@route("GET", "/api/jobs/([\\w-]+)")
def get_job(ctx, jid):
    j = ctx.app.jobs.get(ctx.user["workspace_id"], jid)
    if not j:
        raise KeyError(jid)
    if j.get("run_id"):
        j["run"] = ctx.ws.get("run", j["run_id"])
    return j


@route("GET", "/api/runs")
def list_runs(ctx):
    runs = ctx.ws.list("run", ctx.query.get("product")) if ctx.query.get("product") else ctx.ws.list("run")
    return sorted(runs, key=lambda r: r["created_at"], reverse=True)[:100]


# ---------------- claims, conflicts, decisions ----------------

@route("GET", "/api/products/([\\w-]+)/claims")
def list_claims(ctx, pid):
    claims = list(ctx.ws.claims(pid).values())
    st, q, cat = ctx.query.get("status"), (ctx.query.get("q") or "").lower(), ctx.query.get("category")
    if st:
        claims = [c for c in claims if c["status"] == st]
    if cat:
        claims = [c for c in claims if c["category"] == cat]
    if q:
        claims = [c for c in claims if q in c["text"].lower() or q in c["id"].lower()]
    claims.sort(key=lambda c: int(re.sub(r"\D", "", c["id"]) or 0))
    srcs = {s["id"]: s for s in ctx.ws.list("source", pid)}
    limit = int(ctx.query.get("limit", 500))
    return {"total": len(claims), "claims": [dict(c, source_title=srcs.get(c["source_id"], {}).get("title", c["source_id"]),
                                                  source_url=srcs.get(c["source_id"], {}).get("origin", {}).get("value"))
                                             for c in claims[:limit]]}


@route("GET", "/api/products/([\\w-]+)/review-queue")
def review_queue(ctx, pid):
    product = ctx.ws.product(pid)
    groups = registry.review_queue(ctx.ws.claims(pid))
    srcs = {s["id"]: s for s in ctx.ws.list("source", pid)}
    for g in groups:
        g["bulk_allowed"] = g["category"] not in product["high_risk_categories"]
        g["claims"] = [dict(c, source_title=srcs.get(c["source_id"], {}).get("title", c["source_id"]),
                            source_url=srcs.get(c["source_id"], {}).get("origin", {}).get("value")) for c in g["claims"]]
    return groups


@route("POST", "/api/products/([\\w-]+)/claims/bulk-rule")
def bulk(ctx, pid):
    ids, kind = ctx.need("claim_ids", "kind")
    return actions.bulk_rule(ctx.ws, ctx.user, pid, ids, kind, ctx.body.get("note", ""))


@route("POST", "/api/products/([\\w-]+)/claims/([A-Z0-9]+-\\d+)/rule")
def rule(ctx, pid, cid):
    (kind,) = ctx.need("kind")
    return actions.rule_claim(ctx.ws, ctx.user, pid, cid, kind, ctx.body.get("note", ""))


@route("GET", "/api/products/([\\w-]+)/rulings")
def rulings(ctx, pid):
    return sorted(ctx.ws.list("ruling", pid), key=lambda r: r["created_at"], reverse=True)


@route("GET", "/api/products/([\\w-]+)/conflicts")
def conflicts(ctx, pid):
    claims = ctx.ws.claims(pid)
    srcs = {s["id"]: s for s in ctx.ws.list("source", pid)}
    out = []
    for c in ctx.ws.list("conflict", pid):
        out.append(dict(c, claims=[dict(claims[i], source_title=srcs.get(claims[i]["source_id"], {}).get("title"),
                                        source_kind=srcs.get(claims[i]["source_id"], {}).get("kind"),
                                        source_updated=srcs.get(claims[i]["source_id"], {}).get("updated"))
                                   for i in c["claim_ids"] if i in claims]))
    return sorted(out, key=lambda c: (c["status"] != "open", c["kind"]))


@route("POST", "/api/products/([\\w-]+)/conflicts/([\\w-]+)/rule")
def rule_conflict(ctx, pid, conf_id):
    (note,) = ctx.need("note")
    return actions.rule_conflict(ctx.ws, ctx.user, pid, conf_id, ctx.body.get("keep_claim_id"), note)


@route("GET", "/api/products/([\\w-]+)/decisions")
def decisions(ctx, pid):
    return orchestrator._decisions(ctx.ws, pid)


@route("POST", "/api/products/([\\w-]+)/decisions")
def add_decision(ctx, pid):
    (text,) = ctx.need("text")
    d, diff = actions.save_decision(ctx.ws, ctx.user, pid, text)
    return {"decision": d, "diff": diff}


@route("PUT", "/api/products/([\\w-]+)/decisions/([\\w-]+)")
def edit_decision(ctx, pid, did):
    (text,) = ctx.need("text")
    d, diff = actions.save_decision(ctx.ws, ctx.user, pid, text, decision_id=did)
    return {"decision": d, "diff": diff}


# ---------------- style & positioning ----------------

@route("GET", "/api/products/([\\w-]+)/style-profile")
def style_profile(ctx, pid):
    st = ctx.ws.get("kb-status", pid) or {}
    return {"profile": ctx.ws.get("style-profile", pid), "calibration": st.get("calibration"),
            "threshold": ctx.ws.product(pid).get("style_threshold")}


@route("PUT", "/api/products/([\\w-]+)/style-profile")
def edit_style_profile(ctx, pid):
    actions.require(ctx.user, "product.update")
    prof = ctx.body.get("profile")
    prof = orchestrator.apply_decisions_to_profile(prof, orchestrator._decisions(ctx.ws, pid))
    ctx.ws.put("style-profile", prof, id=pid, product_id=pid)
    ctx.ws.audit(ctx.user["email"], "style.edit", pid)
    return prof


@route("POST", "/api/products/([\\w-]+)/style/accept-threshold")
def accept_threshold(ctx, pid):
    return actions.accept_threshold(ctx.ws, ctx.user, pid, ctx.body.get("threshold"))


@route("GET", "/api/products/([\\w-]+)/positioning")
def positioning(ctx, pid):
    return ctx.ws.get("positioning-pack", pid)


# ---------------- briefs & content ----------------

@route("GET", "/api/content-types")
def list_content_types(ctx):
    return list(orchestrator.content_types(ctx.ws).values())


@route("POST", "/api/content-types")
def add_content_type(ctx):
    actions.require(ctx.user, "product.update")
    ctx.ws.put("content-type", ctx.body)
    ctx.ws.audit(ctx.user["email"], "content-type.save", ctx.body.get("id", "?"))
    return ctx.body


@route("GET", "/api/products/([\\w-]+)/briefs")
def list_briefs(ctx, pid):
    return sorted(ctx.ws.list("brief", pid), key=lambda b: b["created_at"], reverse=True)


@route("POST", "/api/products/([\\w-]+)/briefs")
def new_brief(ctx, pid):
    ctype, title, aud, goal, stage = ctx.need("content_type", "title", "audience", "goal", "stage")
    return actions.create_brief(ctx.ws, ctx.user, pid, ctype, title, aud, goal, stage, ctx.body.get("notes", ""),
                                ctx.body.get("mandated_wording") or [])


@route("POST", "/api/briefs/([\\w-]+)/run")
def run_brief(ctx, bid):
    actions.require(ctx.user, "content.run")
    ws, user, provider = ctx.ws, ctx.user, ctx.app.provider
    b = ws.get("brief", bid)
    if not b:
        raise KeyError(bid)

    def job(progress):
        res = orchestrator.content_run(ws, bid, provider=provider, progress=progress)
        ws.audit(user["email"], "content.run", bid, res["status"])
        return dict({k: res[k] for k in ("run_id", "status", "rounds")}, item_id=bid)
    return {"job_id": ctx.app.jobs.start(ws.workspace_id, "content", job)}


@route("GET", "/api/content")
def list_content(ctx):
    items = ctx.ws.list("content", ctx.query.get("product")) if ctx.query.get("product") else ctx.ws.list("content")
    briefs = {b["id"]: b for b in ctx.ws.list("brief")}
    return sorted([dict(i, brief=briefs.get(i["brief_id"])) for i in items], key=lambda i: i["updated_at"], reverse=True)


def _round_view(ws, item, r):
    out = dict(r)
    out["draft"] = ws.get_text(r["draft_ref"])
    out["report"] = ws.get_json(r["report_ref"]) if r.get("report_ref") and ws.has_object(r["report_ref"]) else None
    vref = f"{r['checks_ref']}/verifier.json"
    if ws.has_object(vref):
        product = ws.product(item["product_id"])
        units = gate.parse_draft(out["draft"])
        out["verdicts"] = gate.enforce(units, ws.get_json(vref), ws.claims(item["product_id"]),
                                       set(product["high_risk_categories"]), item.get("positioning_marks", []))
    return out


@route("GET", "/api/content/([\\w-]+)")
def get_content(ctx, iid):
    item = ctx.ws.get("content", iid)
    if not item:
        raise KeyError(iid)
    claims = ctx.ws.claims(item["product_id"])
    rounds = [_round_view(ctx.ws, item, r) for r in item["rounds"]]
    cited = sorted({i for r in rounds for i in gate.cited_ids(r["draft"])})
    srcs = {s["id"]: s for s in ctx.ws.list("source", item["product_id"])}
    plan = None
    for run in ctx.ws.list("run", item["product_id"]):
        if run.get("brief_id") == item["brief_id"]:
            for s in run["steps"]:
                if s["name"] == "strategist" and s["status"] == "done" and s["output_ref"]:
                    plan = ctx.ws.get_json(s["output_ref"])
    final = ctx.ws.get_text(item["live_version"]["final_ref"]) if item.get("live_version") else None
    return {"item": item, "brief": ctx.ws.get("brief", item["brief_id"]), "rounds": rounds, "plan": plan, "final": final,
            "claims": {i: dict(claims[i], source_title=srcs.get(claims[i]["source_id"], {}).get("title"))
                       for i in cited if i in claims},
            "can_export": gate.can_export(item)}


@route("GET", "/api/content/([\\w-]+)/compare")
def compare(ctx, iid):
    item = ctx.ws.get("content", iid)
    a, b = int(ctx.query.get("a", 1)), int(ctx.query.get("b", len(item["rounds"])))
    ra = _round_view(ctx.ws, item, item["rounds"][a - 1])
    rb = _round_view(ctx.ws, item, item["rounds"][b - 1])
    diff = list(difflib.unified_diff(ra["draft"].splitlines(), rb["draft"].splitlines(), f"round {a}", f"round {b}", lineterm=""))

    def blocks(r):
        return {strip_tags(f.get("sentence", "")).strip(): f for f in (r["report"] or {}).get("flags", []) if f["severity"] == "block"}
    ba, bb = blocks(ra), blocks(rb)
    return {"a": a, "b": b, "diff": diff, "fixed": [ba[k] for k in ba if k not in bb], "new": [bb[k] for k in bb if k not in ba],
            "still": [bb[k] for k in bb if k in ba],
            "status": {"a": (ra["report"] or {}).get("status"), "b": (rb["report"] or {}).get("status")}}


@route("POST", "/api/content/([\\w-]+)/edit")
def edit(ctx, iid):
    actions.require(ctx.user, "content.edit")
    (md,) = ctx.need("draft")
    return orchestrator.human_edit(ctx.ws, iid, md, ctx.user["email"], provider=ctx.app.provider)


@route("POST", "/api/content/([\\w-]+)/direct")
def direct(ctx, iid):
    actions.require(ctx.user, "content.direct")
    (instr,) = ctx.need("instructions")
    ws, user, provider = ctx.ws, ctx.user, ctx.app.provider
    return {"job_id": ctx.app.jobs.start(ws.workspace_id, "direct",
                                         lambda progress: orchestrator.human_directed_revision(ws, iid, instr, user["email"], provider, progress=progress))}


@route("POST", "/api/content/([\\w-]+)/override")
def do_override(ctx, iid):
    actions.require(ctx.user, "content.override")
    (reason,) = ctx.need("reason")
    return orchestrator.override(ctx.ws, iid, reason, ctx.user["email"])


@route("POST", "/api/content/([\\w-]+)/reject")
def do_reject(ctx, iid):
    actions.require(ctx.user, "content.reject")
    return orchestrator.reject(ctx.ws, iid, ctx.user["email"], ctx.body.get("reason", ""))


@route("POST", "/api/content/([\\w-]+)/mark-positioning")
def mark_pos(ctx, iid):
    actions.require(ctx.user, "content.mark-positioning")
    (sentence,) = ctx.need("sentence")
    return orchestrator.mark_positioning(ctx.ws, iid, sentence, ctx.user["email"])


@route("GET", "/api/content/([\\w-]+)/export")
def do_export(ctx, iid):
    data, ctype, fname = actions.export(ctx.ws, ctx.user, iid, ctx.query.get("fmt", "md"), ctx.query.get("citations") == "1")
    return data, ctype, {"Content-Disposition": f"attachment; filename={fname}"}


@route("POST", "/api/products/([\\w-]+)/quick-check")
def quick(ctx, pid):
    actions.require(ctx.user, "content.run")
    (md,) = ctx.need("draft")
    return orchestrator.quick_check(ctx.ws, pid, md, provider=ctx.app.provider)


# ---------------- reports & evals ----------------

@route("GET", "/api/products/([\\w-]+)/gaps")
def gaps(ctx, pid):
    return actions.gaps_report(ctx.ws, pid)


@route("GET", "/api/quality")
def quality(ctx):
    return actions.quality_dashboard(ctx.ws, ctx.query.get("product"))


@route("GET", "/api/cost")
def cost(ctx):
    return actions.cost_dashboard(ctx.ws)


@route("POST", "/api/products/([\\w-]+)/evals/gate")
def eval_gate(ctx, pid):
    actions.require(ctx.user, "eval.run")
    ws, provider = ctx.ws, ctx.app.provider

    def job(progress):
        from evals.cli import run_gate_for_workspace
        return run_gate_for_workspace(ws, pid, provider)
    return {"job_id": ctx.app.jobs.start(ws.workspace_id, "eval", job)}


@route("GET", "/api/products/([\\w-]+)/evals")
def evals(ctx, pid):
    return sorted([e for e in ctx.ws.list("eval") if e.get("product_id") == pid], key=lambda e: e["computed_at"], reverse=True)


# ---------------- server ----------------

def serve(store=None, host="127.0.0.1", port=8780, provider=None):
    store = store or Store()
    app = App(store, provider)
    srv = ThreadingHTTPServer((host, port), make_handler(app))
    print(f"Verified Content Engine on http://{host}:{port}  (data: {store.root}, provider: {os.environ.get('VCE_PROVIDER', 'offline')})")
    srv.serve_forever()
