from __future__ import annotations

import io
import os
import struct
from pathlib import Path
from typing import BinaryIO

from .models import FontFace


NAME_FAMILY = 1
NAME_SUBFAMILY = 2
NAME_FULL = 4
NAME_POSTSCRIPT = 6
NAME_TYPO_FAMILY = 16
NAME_TYPO_SUBFAMILY = 17
NAME_WWS_FAMILY = 21
NAME_WWS_SUBFAMILY = 22

_PREFERRED_LANGS = {0x0409, 0x0809, 0x0C09, 0x0C0C, 0x040C, 0x0000}


def _decode_name(platform_id: int, encoding_id: int, raw: bytes) -> str:
    if not raw:
        return ""
    try:
        if platform_id == 0 or platform_id == 3:
            text = raw.decode("utf-16-be", errors="replace")
        elif platform_id == 1:
            text = raw.decode("mac_roman", errors="replace")
        else:
            text = raw.decode("utf-16-be", errors="replace")
    except Exception:
        text = raw.decode("latin-1", errors="replace")
    return text.replace("\x00", "").strip()


def _choose_name(records: list[tuple[int, int, int, int, str]], name_id: int) -> str:
    candidates = [r for r in records if r[3] == name_id and r[4]]
    if not candidates:
        return ""
    # Prefer Windows English, then any English, then Unicode, then the rest.
    ordered = sorted(
        candidates,
        key=lambda r: (
            0 if (r[0] == 3 and r[1] in (1, 10) and r[2] in _PREFERRED_LANGS) else
            1 if (r[0] == 3 and r[1] in (1, 10)) else
            2 if r[0] == 0 else
            3 if r[0] == 1 else 4,
            r[2] not in _PREFERRED_LANGS,
        ),
    )
    return ordered[0][4]


def _read_name_table(f: BinaryIO, offset: int, length: int) -> list[tuple[int, int, int, int, str]]:
    if offset <= 0 or length < 6 or length > 8 * 1024 * 1024:
        return []
    f.seek(offset)
    header = f.read(6)
    if len(header) < 6:
        return []
    _fmt, count, string_offset = struct.unpack(">HHH", header)
    if count <= 0 or count > 20000:
        return []
    raw_records = f.read(count * 12)
    if len(raw_records) < count * 12:
        return []
    if string_offset >= length:
        return []
    f.seek(offset + string_offset)
    strings = f.read(length - string_offset)
    records: list[tuple[int, int, int, int, str]] = []
    for i in range(count):
        platform_id, encoding_id, language_id, name_id, name_len, name_off = struct.unpack(
            ">HHHHHH", raw_records[i * 12 : (i + 1) * 12]
        )
        rel = name_off
        if rel < 0 or rel + name_len > len(strings) or name_len <= 0:
            continue
        text = _decode_name(platform_id, encoding_id, strings[rel : rel + name_len])
        if text:
            records.append((platform_id, encoding_id, language_id, name_id, text))
    return records


def _table_directory(f: BinaryIO, offset: int) -> tuple[dict[bytes, tuple[int, int, int]], int, bool]:
    f.seek(offset)
    header = f.read(12)
    if len(header) < 12:
        return {}, 0, False
    tag = header[:4]
    num_tables = struct.unpack(">H", header[4:6])[0]
    if tag not in (b"\x00\x01\x00\x00", b"OTTO", b"true", b"typ1") or num_tables <= 0 or num_tables > 4096:
        return {}, 0, False
    records = f.read(num_tables * 16)
    if len(records) < num_tables * 16:
        return {}, 0, False
    tables: dict[bytes, tuple[int, int, int]] = {}
    for i in range(num_tables):
        rec = records[i * 16 : (i + 1) * 16]
        table_tag = rec[:4]
        _checksum, table_offset, table_length = struct.unpack(">III", rec[4:16])
        tables[table_tag] = (table_offset, table_length, i)
    return tables, num_tables, True


def _parse_face(
    f: BinaryIO,
    face_offset: int,
    source: str,
    path: str | None,
    face_index: int,
    file_format: str,
) -> FontFace | None:
    tables, _num_tables, valid = _table_directory(f, face_offset)
    if not valid or b"name" not in tables:
        return None
    name_offset, name_length, _ = tables[b"name"]
    records = _read_name_table(f, name_offset, name_length)
    if not records:
        return None

    family = _choose_name(records, NAME_TYPO_FAMILY) or _choose_name(records, NAME_FAMILY)
    subfamily = _choose_name(records, NAME_TYPO_SUBFAMILY) or _choose_name(records, NAME_SUBFAMILY)
    full_name = _choose_name(records, NAME_FULL)
    postscript = _choose_name(records, NAME_POSTSCRIPT)
    if not family:
        family = full_name or postscript
    if not family:
        return None

    aliases: list[str] = []
    for name_id in (NAME_FAMILY, NAME_TYPO_FAMILY, NAME_FULL, NAME_POSTSCRIPT, NAME_WWS_FAMILY):
        for rec in records:
            if rec[3] == name_id and rec[4]:
                if rec[4] not in aliases and rec[4] != family:
                    aliases.append(rec[4])

    weight = 400
    if b"OS/2" in tables:
        os2_offset, os2_len, _ = tables[b"OS/2"]
        if os2_len >= 6:
            f.seek(os2_offset + 4)
            raw = f.read(2)
            if len(raw) == 2:
                candidate = struct.unpack(">H", raw)[0]
                if 1 <= candidate <= 1000:
                    weight = candidate
    is_variable = b"fvar" in tables

    return FontFace(
        family=family.strip(),
        subfamily=subfamily.strip(),
        full_name=full_name.strip(),
        postscript_name=postscript.strip(),
        aliases=tuple(aliases),
        path=path,
        face_index=face_index,
        source=source,
        is_variable=is_variable,
        weight=weight,
        file_format=file_format,
    )


def read_font_faces_from_file(path: str | os.PathLike[str], source: str = "system") -> list[FontFace]:
    p = Path(path)
    suffix = p.suffix.lower().lstrip(".")
    try:
        with open(p, "rb") as f:
            header = f.read(12)
            if len(header) < 12:
                return []
            if header[:4] == b"ttcf":
                _version, num_fonts = struct.unpack(">II", header[4:12])
                if num_fonts <= 0 or num_fonts > 4096:
                    return []
                offsets_raw = f.read(num_fonts * 4)
                if len(offsets_raw) < num_fonts * 4:
                    return []
                offsets = struct.unpack(f">{num_fonts}I", offsets_raw)
                faces: list[FontFace] = []
                for idx, offset in enumerate(offsets):
                    try:
                        face = _parse_face(f, offset, source, str(p), idx, suffix)
                    except Exception:
                        face = None
                    if face:
                        faces.append(face)
                return faces
            face = _parse_face(f, 0, source, str(p), 0, suffix)
            return [face] if face else []
    except (OSError, struct.error, ValueError):
        return []


def read_font_faces_from_bytes(data: bytes, source: str = "embedded", label: str = "") -> list[FontFace]:
    if len(data) < 12:
        return []
    suffix = Path(label).suffix.lower().lstrip(".") if label else ""
    f = io.BytesIO(data)
    try:
        header = f.read(12)
        if header[:4] == b"ttcf":
            _version, num_fonts = struct.unpack(">II", header[4:12])
            if num_fonts <= 0 or num_fonts > 4096:
                return []
            offsets_raw = f.read(num_fonts * 4)
            offsets = struct.unpack(f">{num_fonts}I", offsets_raw)
            faces: list[FontFace] = []
            for idx, offset in enumerate(offsets):
                try:
                    face = _parse_face(f, offset, source, None, idx, suffix)
                except Exception:
                    face = None
                if face:
                    faces.append(face)
            return faces
        face = _parse_face(f, 0, source, None, 0, suffix)
        return [face] if face else []
    except (OSError, struct.error, ValueError):
        return []


def describe(path: str | os.PathLike[str]) -> str:
    faces = read_font_faces_from_file(path)
    if not faces:
        return f"{Path(path).name}（无法读取字体信息）"
    return " / ".join(f"{f.family} {f.subfamily}".strip() for f in faces[:4])
