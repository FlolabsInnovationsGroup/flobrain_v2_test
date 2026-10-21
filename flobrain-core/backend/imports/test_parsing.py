"""Parsing without the database: Slack messages and markup, Notion blocks and exports, file text."""

import io
import zipfile
from unittest.mock import patch

from django.test import SimpleTestCase

from imports import notion, services, slack, textract
from imports.safezip import SafeZip


def msg(ts, user="U1", text="hi", **extra):
    return {"type": "message", "ts": ts, "user": user, "text": text, **extra}


class SlackParsingTests(SimpleTestCase):
    def test_threads_edits_bots_and_joins(self):
        raw = [
            msg("1700000000.000100", text="Root"),
            msg("1700000001.000100", subtype="channel_join", text="<@U2> has joined the channel"),
            msg("1700000002.000100", user="U2", text="Reply", thread_ts="1700000000.000100"),
            msg("1700000003.000100", subtype="bot_message", bot_id="B1", text="Deployed"),
            msg("1700000004.000100", user="U3", text="from an app", bot_id="B2"),
            {"type": "message", "subtype": "message_changed", "ts": "1700000005.000000", "message": {"ts": "1700000000.000100", "text": "Root, fixed"}},
            msg("1700000006.000100", text="gone"),
            {"type": "message", "subtype": "message_deleted", "deleted_ts": "1700000006.000100", "ts": "1700000007.0"},
            msg("not-a-ts", text="bad"),
            msg("1700000008.000100", text="", files=[{"title": "Plan.pdf", "permalink": "https://x.slack.com/files/U1/F1/plan.pdf"}]),
            msg("1700000009.000100", subtype="channel_topic", text="set the topic"),
            {"type": "message", "ts": "1700000010.000100", "user": "U1", "text": "edited later", "edited": {"user": "U1", "ts": "1700000011.0"}},
        ]
        out = slack.parse_messages(raw)
        self.assertEqual([m.text for m in out], ["Root, fixed", "Reply", "", "edited later"])
        self.assertTrue(out[0].edited)
        self.assertTrue(out[1].is_reply)
        self.assertFalse(out[0].is_reply)
        self.assertEqual(out[2].files, [("Plan.pdf", "https://x.slack.com/files/U1/F1/plan.pdf")])
        self.assertTrue(out[3].edited)
        with_bots = slack.parse_messages(raw, include_bots=True)
        self.assertIn("Deployed", [m.text for m in with_bots])

    def test_reactions_and_unsafe_file_links(self):
        out = slack.parse_messages([msg("1700000000.1", reactions=[{"name": "thumbsup", "users": ["U1", "U2"], "count": 2}, {"name": "<script>", "count": 1}], files=[{"name": "x", "permalink": "javascript:alert(1)"}])])
        self.assertEqual(out[0].reactions, [("thumbsup", 2), ("script", 1)])
        self.assertEqual(out[0].files, [("x", "")])
        self.assertEqual(slack.reactions_line(out[0].reactions), "Reactions: :thumbsup: 2, :script: 1")

    def test_convert_text(self):
        names = {"U1": "Layla Mansour"}
        text = "Hi <@U1>, see <#C9|general> and <https://example.com/a?b=1&amp;c=2|the doc> or <https://example.com>. <!here> <@U404> <mailto:a@b.co|a@b.co> <javascript:alert(1)|click> &lt;b&gt;"
        out = slack.convert_text(text, names, {})
        self.assertIn("@Layla Mansour", out)
        self.assertIn("#general", out)
        self.assertIn("the doc (https://example.com/a?b=1&c=2)", out)
        self.assertIn("@here", out)
        self.assertIn("@someone", out)
        self.assertIn("a@b.co", out)
        self.assertNotIn("javascript", out)
        self.assertIn("<b>", out)  # entities decoded; nothing renders it as HTML

    def test_fixture_export(self):
        with SafeZip(services.fixture_zip("slack_export")) as zf:
            export = slack.SlackExport(zf)
            self.assertEqual({c.name: c.kind for c in export.channels}, {"general": "public", "engineering": "public", "design-crit": "private"})
            total = sum(len(export.messages(c)) for c in export.channels)
            self.assertEqual(total, 150)
            replies = sum(1 for c in export.channels for m in export.messages(c) if m.is_reply)
            self.assertGreater(replies, 10)

    def test_export_in_a_top_folder_and_not_slack(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("My Export/users.json", '[{"id": "U1", "real_name": "A", "profile": {"email": "A@x.com"}}]')
            zf.writestr("My Export/channels.json", '[{"id": "C1", "name": "general", "members": ["U1"]}]')
            zf.writestr("My Export/general/2026-01-01.json", '[{"type": "message", "ts": "1767225600.0001", "user": "U1", "text": "hello"}]')
        export = slack.SlackExport(SafeZip(io.BytesIO(buf.getvalue())))
        self.assertEqual(export.users["U1"].email, "a@x.com")
        self.assertEqual(len(export.messages(export.channels[0])), 1)
        other = io.BytesIO()
        with zipfile.ZipFile(other, "w") as zf:
            zf.writestr("notes.txt", "x")
        with self.assertRaises(slack.SlackError):
            slack.SlackExport(SafeZip(io.BytesIO(other.getvalue())))


class NotionTests(SimpleTestCase):
    def rt(self, text, href=None):
        return [{"plain_text": text, "href": href}]

    def test_blocks_to_markdown(self):
        blocks = [
            {"block": {"type": "heading_1", "heading_1": {"rich_text": self.rt("Plan")}}},
            {"block": {"type": "paragraph", "paragraph": {"rich_text": self.rt("See ") + self.rt("docs", "https://example.com/d")}}},
            {"block": {"type": "bulleted_list_item", "bulleted_list_item": {"rich_text": self.rt("One")}}, "children": [
                {"block": {"type": "bulleted_list_item", "bulleted_list_item": {"rich_text": self.rt("Nested")}}}]},
            {"block": {"type": "numbered_list_item", "numbered_list_item": {"rich_text": self.rt("First")}}},
            {"block": {"type": "to_do", "to_do": {"rich_text": self.rt("Done thing"), "checked": True}}},
            {"block": {"type": "table", "table": {}}, "children": [
                {"block": {"type": "table_row", "table_row": {"cells": [self.rt("A"), self.rt("B")]}}},
                {"block": {"type": "table_row", "table_row": {"cells": [self.rt("1"), self.rt("2")]}}}]},
            {"block": {"type": "code", "code": {"rich_text": self.rt("print(1)")}}},
            {"block": {"type": "image", "image": {"type": "file", "file": {"url": "https://s3.amazonaws.com/secret?sig=x"}}}},
            {"block": {"type": "child_page", "child_page": {"title": "Sub"}}},
        ]
        md = notion.blocks_to_markdown(blocks)
        self.assertIn("# Plan", md)
        self.assertIn("See docs (https://example.com/d)", md)
        self.assertIn("- One\n  - Nested", md)
        self.assertIn("1. First", md)
        self.assertIn("- [x] Done thing", md)
        self.assertIn("A | B\n1 | 2", md)
        self.assertIn("```\nprint(1)\n```", md)
        self.assertIn("[Image]", md)
        self.assertNotIn("amazonaws", md)  # signed file links expire and leak access; never kept
        self.assertIn("Subpage: Sub", md)

    def test_simplify_markdown(self):
        text = "<aside>\n💡 Tip\n</aside>\n\n| A | B |\n| --- | --- |\n| 1 | 2 |\n\n[Other page](Other%20page%20abc.md) ![pic](pic.png)"
        out = notion.simplify_markdown(text)
        self.assertNotIn("<aside>", out)
        self.assertIn("A | B\n1 | 2", out)
        self.assertNotIn("---", out)
        self.assertIn("Other page", out)
        self.assertNotIn(".md)", out)
        self.assertIn("[Image: pic]", out)

    def test_fixture_export(self):
        export = notion.NotionExport(SafeZip(services.fixture_zip("notion_export")))
        by_title = {i["title"]: i for i in export.items}
        self.assertEqual(set(by_title), {"Team handbook", "Onboarding checklist", "Release process", "Customers"})
        self.assertEqual(by_title["Customers"]["kind"], "database")
        self.assertTrue(by_title["Customers"]["name"].endswith("_all.csv"))
        title, text = export.document(by_title["Onboarding checklist"])
        self.assertEqual(title, "Onboarding checklist")
        self.assertIn("Sunday | Product tour | Layla", text)
        self.assertEqual(by_title["Team handbook"]["notion_id"], "1a2b3c4d5e6f40718293a4b5c6d7e8f9")

    def test_nested_export_zip(self):
        inner = services.fixture_zip("notion_export").getvalue()
        outer = io.BytesIO()
        with zipfile.ZipFile(outer, "w") as zf:
            zf.writestr("Export-1234.zip", inner)
        export = notion.NotionExport(SafeZip(io.BytesIO(outer.getvalue())))
        self.assertEqual(len(export.items), 4)

    def test_prop_text(self):
        self.assertEqual(notion.prop_text({"type": "multi_select", "multi_select": [{"name": "A"}, {"name": "B"}]}), "A, B")
        self.assertEqual(notion.prop_text({"type": "checkbox", "checkbox": True}), "Yes")
        self.assertEqual(notion.prop_text({"type": "date", "date": {"start": "2026-01-01", "end": "2026-01-02"}}), "2026-01-01 to 2026-01-02")


def docx_bytes() -> bytes:
    w = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
    xml = f"""<?xml version="1.0" encoding="UTF-8"?><w:document {w}><w:body>
<w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr><w:r><w:t>Handbook</w:t></w:r></w:p>
<w:p><w:r><w:t>Welcome to the team.</w:t></w:r></w:p>
<w:p><w:pPr><w:numPr><w:ilvl w:val="0"/></w:numPr></w:pPr><w:r><w:t>Bring your laptop</w:t></w:r></w:p>
<w:tbl><w:tr><w:tc><w:p><w:r><w:t>Day</w:t></w:r></w:p></w:tc><w:tc><w:p><w:r><w:t>Who</w:t></w:r></w:p></w:tc></w:tr></w:tbl>
</w:body></w:document>"""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("[Content_Types].xml", "<Types/>")
        zf.writestr("word/document.xml", xml)
    return buf.getvalue()


class TextractTests(SimpleTestCase):
    def test_docx(self):
        text = textract.extract("Handbook.docx", docx_bytes())
        self.assertIn("# Handbook", text)
        self.assertIn("- Bring your laptop", text)
        self.assertIn("Day | Who", text)

    def test_hostile_docx_is_refused(self):
        evil = io.BytesIO()
        with zipfile.ZipFile(evil, "w") as zf:
            zf.writestr("word/document.xml", '<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "aaaa"><!ENTITY b "&a;&a;&a;">]><x>&b;</x>')
        with self.assertRaises(textract.ExtractError):
            textract.extract("evil.docx", evil.getvalue())
        with self.assertRaises(textract.ExtractError):
            textract.extract("broken.docx", b"not a zip")

    def test_html_csv_txt(self):
        self.assertEqual(textract.extract("a.html", b"<h1>Title</h1><script>alert(1)</script><p>Body</p>"), "# Title\n\nBody")
        self.assertEqual(textract.extract("a.csv", b"a,b\n1,2\n"), "a | b\n1 | 2")
        self.assertEqual(textract.extract("a.md", "﻿# Hi".encode()), "# Hi")
        with self.assertRaises(textract.ExtractError):
            textract.extract("a.exe", b"MZ")

    def test_broken_pdf_is_unreadable_not_a_crash(self):
        if not textract.pdf_supported():
            self.skipTest("pypdf not installed")
        with self.assertRaises(textract.ExtractError) as ctx:
            textract.extract("a.pdf", b"%PDF-1.4 not really a pdf")
        self.assertEqual(ctx.exception.code, "unreadable")

    def test_pdf_without_pypdf_is_reported(self):
        with patch.dict("sys.modules", {"pypdf": None}):
            self.assertFalse(textract.pdf_supported())
            with self.assertRaises(textract.ExtractError) as ctx:
                textract.extract("a.pdf", b"%PDF-1.4")
            self.assertEqual(ctx.exception.code, "pdf_unavailable")
