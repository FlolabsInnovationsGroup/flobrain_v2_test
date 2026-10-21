"""Reading uploaded ZIP archives safely (Slack exports, Notion exports, Google Takeout, DOCX).

Nothing is ever extracted to disk: members are read into memory one at a time, with a byte cap.
The whole archive is refused before anything is read when any entry is unsafe:

- a name that is absolute (``/x``, ``\\x``, ``C:x``), contains ``..`` as a path part, a NUL byte
  or a backslash, or is longer than 512 characters;
- a symbolic link (Unix mode in ``external_attr``) or an encrypted entry;
- more than ``max_files`` entries, more than ``max_total`` uncompressed bytes in total, or one
  entry bigger than ``max_member``;
- an entry whose uncompressed size is more than ``max_ratio`` times its compressed size (zip
  bomb), once it is past 1 MB.

Declared sizes in the ZIP headers can lie, so reads also stop at the declared size: a member
that inflates past it is refused (``ZipSafetyError("bomb")``) and the running total is checked
against ``max_total`` again.
"""

import stat
import zipfile
from dataclasses import dataclass

READ_CHUNK = 1 << 16
RATIO_FLOOR = 1 << 20  # small entries compress very well (JSON of zeros); only judge big ones


class ZipSafetyError(Exception):
    """The archive is refused. ``code`` is one of: not_zip, traversal, absolute, symlink,
    encrypted, too_many_files, too_big, bomb, bad_name."""

    def __init__(self, code: str, details: str = ""):
        super().__init__(details or code)
        self.code = code
        self.details = details or code


@dataclass(frozen=True)
class Limits:
    max_files: int = 20000
    max_total: int = 2 * 1024**3  # 2 GB uncompressed
    max_member: int = 200 * 1024**2
    max_ratio: int = 100


def _bad_name(name: str) -> str:
    """Return an error code for an unsafe member name, or ''."""
    if not name or len(name) > 512 or "\x00" in name:
        return "bad_name"
    if "\\" in name:
        return "traversal"
    if name.startswith("/") or (len(name) > 1 and name[1] == ":"):
        return "absolute"
    if any(part == ".." for part in name.split("/")):
        return "traversal"
    return ""


def _is_symlink(info: zipfile.ZipInfo) -> bool:
    mode = (info.external_attr >> 16) & 0xFFFF
    return bool(mode) and stat.S_ISLNK(mode)


class SafeZip:
    """A checked archive. Use ``names()`` and ``read(name)``; never ``extractall``."""

    def __init__(self, fileobj, limits: Limits | None = None):
        self.limits = limits or Limits()
        try:
            self._zip = zipfile.ZipFile(fileobj)
        except (zipfile.BadZipFile, OSError, ValueError) as exc:
            raise ZipSafetyError("not_zip", "This file is not a ZIP archive") from exc
        self._read_total = 0
        self._infos: dict[str, zipfile.ZipInfo] = {}
        self._check()

    def _check(self) -> None:
        lim = self.limits
        infos = self._zip.infolist()
        if len(infos) > lim.max_files:
            raise ZipSafetyError("too_many_files", f"The archive has more than {lim.max_files} files")
        total = 0
        for info in infos:
            code = _bad_name(info.filename)
            if code:
                raise ZipSafetyError(code, "The archive has a file with an unsafe name")
            if _is_symlink(info):
                raise ZipSafetyError("symlink", "The archive contains a link, which is not allowed")
            if info.flag_bits & 0x1:
                raise ZipSafetyError("encrypted", "Password-protected archives are not supported")
            if info.is_dir():
                continue
            if info.file_size > lim.max_member:
                raise ZipSafetyError("too_big", "A file in the archive is too big")
            total += info.file_size
            if total > lim.max_total:
                raise ZipSafetyError("too_big", "The archive is too big once unpacked")
            if info.file_size > RATIO_FLOOR and info.file_size > lim.max_ratio * max(info.compress_size, 1):
                raise ZipSafetyError("bomb", "The archive looks like a zip bomb")
            self._infos[info.filename] = info

    def names(self) -> list[str]:
        return list(self._infos)

    def size(self, name: str) -> int:
        return self._infos[name].file_size

    def read(self, name: str, max_bytes: int | None = None) -> bytes:
        """Read one member, never more than its declared size (and ``max_bytes`` when given)."""
        info = self._infos.get(name)
        if info is None:
            raise KeyError(name)
        cap = info.file_size if max_bytes is None else min(info.file_size, max_bytes)
        if max_bytes is not None and info.file_size > max_bytes:
            raise ZipSafetyError("too_big", "A file in the archive is too big")
        out = bytearray()
        try:
            with self._zip.open(info) as fh:
                while True:
                    chunk = fh.read(READ_CHUNK)
                    if not chunk:
                        break
                    out.extend(chunk)
                    if len(out) > cap:
                        raise ZipSafetyError("bomb", "A file in the archive is bigger than it says")
        except (zipfile.BadZipFile, EOFError, OSError, NotImplementedError) as exc:
            raise ZipSafetyError("not_zip", "A file in the archive is damaged") from exc
        self._read_total += len(out)
        if self._read_total > self.limits.max_total:
            raise ZipSafetyError("too_big", "The archive is too big once unpacked")
        return bytes(out)

    def close(self) -> None:
        self._zip.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
