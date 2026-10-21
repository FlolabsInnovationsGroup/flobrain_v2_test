"""Zip safety: traversal, absolute paths, symlinks, bombs, file count, lying sizes, not a zip."""

import io
import stat
import zipfile

from django.test import SimpleTestCase

from imports.safezip import Limits, SafeZip, ZipSafetyError


def make_zip(entries, compression=zipfile.ZIP_DEFLATED) -> io.BytesIO:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression) as zf:
        for entry in entries:
            if isinstance(entry, zipfile.ZipInfo):
                zf.writestr(entry, b"target")
            else:
                name, data = entry
                zf.writestr(name, data)
    buf.seek(0)
    return buf


class SafeZipTests(SimpleTestCase):
    def refused(self, buf, code, limits=None):
        with self.assertRaises(ZipSafetyError) as ctx:
            SafeZip(buf, limits)
        self.assertEqual(ctx.exception.code, code)

    def test_reads_a_normal_archive(self):
        with SafeZip(make_zip([("a/b.json", b"[1]"), ("c.txt", b"hi")])) as zf:
            self.assertEqual(sorted(zf.names()), ["a/b.json", "c.txt"])
            self.assertEqual(zf.read("c.txt"), b"hi")

    def test_path_traversal_is_refused(self):
        self.refused(make_zip([("ok.txt", b"x"), ("../../etc/passwd", b"x")]), "traversal")
        self.refused(make_zip([("a/../../b.txt", b"x")]), "traversal")
        self.refused(make_zip([("a\\..\\b.txt", b"x")]), "traversal")

    def test_absolute_paths_are_refused(self):
        self.refused(make_zip([("/etc/passwd", b"x")]), "absolute")
        self.refused(make_zip([("C:/Windows/x.txt", b"x")]), "absolute")

    def test_symlinks_are_refused(self):
        link = zipfile.ZipInfo("link")
        link.external_attr = (stat.S_IFLNK | 0o777) << 16
        self.refused(make_zip([("a.txt", b"x"), link]), "symlink")

    def test_zip_bomb_ratio_is_refused(self):
        self.refused(make_zip([("zeros.json", b"0" * (5 * 1024 * 1024))]), "bomb")

    def test_small_compressible_files_are_fine(self):
        SafeZip(make_zip([("zeros.json", b"0" * 100_000)]))

    def test_file_count_and_total_size_limits(self):
        self.refused(make_zip([(f"f{i}.txt", b"x") for i in range(11)]), "too_many_files", Limits(max_files=10))
        self.refused(make_zip([("a.txt", b"x" * 600), ("b.txt", b"y" * 600)], zipfile.ZIP_STORED), "too_big", Limits(max_total=1000))
        self.refused(make_zip([("a.txt", b"x" * 600)], zipfile.ZIP_STORED), "too_big", Limits(max_member=500))

    def test_not_a_zip(self):
        self.refused(io.BytesIO(b"PK\x03\x04 not really"), "not_zip")
        self.refused(io.BytesIO(b"hello"), "not_zip")

    def test_read_cap(self):
        with SafeZip(make_zip([("a.txt", b"x" * 100)])) as zf:
            with self.assertRaises(ZipSafetyError):
                zf.read("a.txt", max_bytes=10)
            with self.assertRaises(KeyError):
                zf.read("missing.txt")

    def test_a_member_that_lies_about_its_size_stops_at_the_declared_size(self):
        raw = bytearray(make_zip([("a.txt", b"x" * 5000)], zipfile.ZIP_STORED).getvalue())
        # Shrink the declared size in the central directory: the read must never hand back 5000 bytes.
        cd = raw.rfind(b"PK\x01\x02")
        raw[cd + 24:cd + 28] = (100).to_bytes(4, "little")
        with SafeZip(io.BytesIO(bytes(raw))) as safe:
            self.assertEqual(safe.size("a.txt"), 100)
            with self.assertRaises(ZipSafetyError):
                safe.read("a.txt")
