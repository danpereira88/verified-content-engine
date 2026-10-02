import io
import zipfile

from tests.helpers import ADMIN, StoreCase, unittest
from services import actions, ingest


def _docx(paras):
    def ppr(style):
        return f'<w:pPr><w:pStyle w:val="{style}"/></w:pPr>' if style else ""
    body = "".join(f"<w:p>{ppr(s)}<w:r><w:t>{t}</w:t></w:r></w:p>" for s, t in paras)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("word/document.xml", f'<w:document xmlns:w="x"><w:body>{body}</w:body></w:document>')
    return buf.getvalue()


def _pptx(slides):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for i, texts in enumerate(slides, 1):
            ps = "".join(f"<a:p><a:r><a:t>{t}</a:t></a:r></a:p>" for t in texts)
            z.writestr(f"ppt/slides/slide{i}.xml", f'<p:sld xmlns:a="a" xmlns:p="p">{ps}</p:sld>')
    return buf.getvalue()


class ParserTests(unittest.TestCase):
    def test_markdown_locations_and_frontmatter(self):
        meta, blocks = ingest.parse_markdown("---\ntitle: Spec\nkind: living\nupdated: 2026-01-01\n---\n# Spec\n## Limits\nOne fact.\n\nTwo fact.\n- A bullet.\n")
        self.assertEqual(meta["kind"], "living")
        locs = [b["loc"] for b in blocks]
        self.assertIn("Spec > Limits ¶1", locs)
        self.assertIn("Spec > Limits ¶3", locs)

    def test_html(self):
        meta, blocks = ingest.parse_html("<html><head><title>T</title><script>x()</script></head><body><nav>menu</nav>"
                                         "<h1>Docs</h1><p>Acme stores data.</p><ul><li>Item</li></ul></body></html>")
        self.assertEqual(meta["title"], "T")
        texts = [b["text"] for b in blocks]
        self.assertEqual(texts, ["Docs", "Acme stores data.", "Item"])

    def test_docx(self):
        meta, blocks = ingest.parse_docx(_docx([("Heading1", "Overview"), ("", "Acme stores data for 30 days.")]))
        self.assertEqual(blocks[1]["loc"], "Overview ¶1")

    def test_pptx(self):
        meta, blocks = ingest.parse_pptx(_pptx([["Title"], ["Point one", "Point two"]]))
        self.assertEqual([b["loc"] for b in blocks], ["Slide 1 ¶1", "Slide 2 ¶1", "Slide 2 ¶2"])

    def test_unsupported_type(self):
        with self.assertRaises(ingest.IngestError):
            ingest.parse_file("x.exe", b"")


class SnapshotTests(StoreCase):
    def setUp(self):
        super().setUp()
        actions.create_product(self.ws, ADMIN, "Acme Box", "ACME", slug="acme")

    def test_snapshot_is_stable_per_origin_and_detects_change(self):
        s1, ch1, _ = actions.add_source(self.ws, ADMIN, "acme", "truth", "spec.md", b"# Spec\nAcme stores data.\n")
        s2, ch2, _ = actions.add_source(self.ws, ADMIN, "acme", "truth", "spec.md", b"# Spec\nAcme stores data.\n")
        self.assertTrue(ch1)
        self.assertFalse(ch2)
        s3, ch3, stale = actions.add_source(self.ws, ADMIN, "acme", "truth", "spec.md", b"# Spec\nAcme keeps data.\n")
        self.assertTrue(ch3)
        self.assertEqual(s1["id"], s3["id"])
        self.assertNotEqual(s1["sha256"], s3["sha256"])
        # both versions remain stored
        self.assertTrue(self.ws.has_object(f"acme/sources/{s1['id']}/{s1['sha256']}.raw"))

    def test_evidence_requires_workspace_setting(self):
        actions.create_product(self.wsb, ADMIN, "Acme Box", "ACME", slug="acme")
        with self.assertRaises(ingest.IngestError):
            actions.add_source(self.wsb, ADMIN, "acme", "evidence", "survey.json", b'{"responses": [{"id": "R1", "answers": {"a": "b"}}]}')

    def test_role_required(self):
        from services.actions import Forbidden
        with self.assertRaises(Forbidden):
            actions.add_source(self.ws, {"email": "x", "roles": ["reviewer"]}, "acme", "truth", "a.md", b"# A\nB c d e f.\n")


if __name__ == "__main__":
    unittest.main()
