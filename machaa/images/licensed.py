"""Find one reusable reference image, or say plainly that none was found.

Wikimedia Commons and Openverse are the only sources. A licence that
forbids commercial use or derivatives is skipped. Machaa never invents a
photograph: the file is either the downloaded image or a drawn placeholder.
"""

from __future__ import annotations

import html
import json
import re
import urllib.error
import urllib.parse
import urllib.request
import zlib
import struct
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from machaa.core.guardian import Guardian

USER_AGENT = "Machaa/0.2 (+https://github.com/Karthikrapolu-ai/machaa)"
MAX_BYTES = 4_000_000
_TAG = re.compile(r"<[^>]+>")
_REJECT = re.compile(
    r"(\bnc\b|\bnd\b|non[\s-]?commercial|noderiv|no[\s-]?deriv)",
    re.IGNORECASE,
)
_ACCEPT = re.compile(
    r"(public domain|\bcc0\b|cc[\s-]?zero|\bpdm\b|creative commons attribution|"
    r"\battribution\b|\bcc[\s-]?by(?:[\s-]?sa)?\b|\bby[\s-]?sa\b)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class ImageResult:
    placeholder: bool
    path: Path | None
    title: str = ""
    artist: str = ""
    license_name: str = ""
    license_url: str = ""
    source_page: str = ""
    file_url: str = ""

    @property
    def reusable(self) -> bool:
        return not self.placeholder and self.path is not None


@dataclass(frozen=True)
class Candidate:
    title: str
    artist: str
    license_name: str
    license_url: str
    source_page: str
    file_url: str


def license_is_reusable(name: str) -> bool:
    """Public domain, CC0, CC BY, and CC BY-SA only. NC and ND are refused."""

    text = " ".join((name or "").replace("_", " ").split())
    if not text or _REJECT.search(text):
        return False
    return _ACCEPT.search(text) is not None


def find_licensed_image(query: str, dest_dir: Path, guardian: Guardian) -> ImageResult:
    """Search Commons, then Openverse. Save one image or a labelled placeholder."""

    dest_dir.mkdir(parents=True, exist_ok=True)
    downloads = 0
    for attempt in _query_attempts(query):
        for candidate in _search_commons(attempt) + _search_openverse(attempt):
            if not _usable(candidate) or not _on_topic(candidate, query):
                continue
            downloads += 1
            saved = _download(candidate, dest_dir, guardian)
            if saved is not None:
                return ImageResult(
                    placeholder=False,
                    path=saved,
                    title=candidate.title,
                    artist=candidate.artist,
                    license_name=candidate.license_name,
                    license_url=candidate.license_url,
                    source_page=candidate.source_page,
                    file_url=candidate.file_url,
                )
            if downloads >= 3:
                break
        if downloads >= 3:
            break
    placeholder = dest_dir / "reference-placeholder.png"
    _write_placeholder_png(placeholder)
    return ImageResult(placeholder=True, path=placeholder)


_ROOMISH = re.compile(
    r"(room|interior|apartment|kitchen|bedroom|living|sofa|furniture|home)",
    re.IGNORECASE,
)


def _query_attempts(query: str) -> list[str]:
    """Try the asked phrase. A long marketing line often misses, so a room search follows."""

    cleaned = " ".join((query or "").split())
    attempts: list[str] = []

    def add(value: str) -> None:
        value = " ".join(value.split())[:200]
        if value and value not in attempts:
            attempts.append(value)

    add(cleaned)
    lowered = cleaned.lower()
    if any(word in lowered for word in ("interior", "bhk", "room", "home", "apartment", "design")):
        add("apartment living room")
    return attempts or ["interior"]


def _on_topic(candidate: Candidate, query: str) -> bool:
    """An interior request should not embed a photo whose title is unrelated."""

    lowered = (query or "").lower()
    if not any(word in lowered for word in ("interior", "bhk", "room", "home", "apartment")):
        return True
    return _ROOMISH.search(candidate.title or "") is not None


def _usable(candidate: Candidate) -> bool:
    return _first_reusable([candidate]) is not None


def _first_reusable(candidates: list[Candidate]) -> Candidate | None:
    for candidate in candidates:
        if not license_is_reusable(candidate.license_name):
            continue
        if not candidate.file_url.startswith("https://"):
            continue
        if not _allowed_image_host(candidate.file_url):
            continue
        return candidate
    return None


def _search_commons(query: str) -> list[Candidate]:
    params = urllib.parse.urlencode(
        {
            "action": "query",
            "format": "json",
            "generator": "search",
            "gsrsearch": query[:200],
            "gsrnamespace": "6",
            "gsrlimit": "8",
            "prop": "imageinfo",
            "iiprop": "url|size|mime|extmetadata",
            "iiurlwidth": "1024",
        }
    )
    url = "https://commons.wikimedia.org/w/api.php?" + params
    try:
        payload = _get_json(url)
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, ValueError):
        return []
    pages = (payload.get("query") or {}).get("pages") if isinstance(payload, dict) else None
    if not isinstance(pages, dict):
        return []
    found: list[Candidate] = []
    for page in pages.values():
        if not isinstance(page, dict):
            continue
        infos = page.get("imageinfo")
        if not isinstance(infos, list) or not infos or not isinstance(infos[0], dict):
            continue
        info = infos[0]
        meta = info.get("extmetadata") if isinstance(info.get("extmetadata"), dict) else {}
        license_name = _meta(meta, "LicenseShortName") or _meta(meta, "License") or _meta(meta, "UsageTerms")
        file_url = str(info.get("thumburl") or "")
        if not file_url:
            size = info.get("size")
            mime = str(info.get("mime") or "")
            if isinstance(size, int) and size <= MAX_BYTES and mime in {"image/jpeg", "image/png"}:
                file_url = str(info.get("url") or "")
        title = str(page.get("title") or "").removeprefix("File:").replace("_", " ")
        found.append(
            Candidate(
                title=_plain(title)[:200] or "Wikimedia Commons image",
                artist=_plain(_meta(meta, "Artist") or _meta(meta, "Credit"))[:200] or "unknown artist",
                license_name=_plain(license_name)[:120],
                license_url=_plain(_meta(meta, "LicenseUrl"))[:500],
                source_page=str(info.get("descriptionurl") or "")[:500],
                file_url=file_url[:1000],
            )
        )
    return found


def _search_openverse(query: str) -> list[Candidate]:
    params = urllib.parse.urlencode(
        {
            "q": query[:200],
            "license": "cc0,pdm,by,by-sa",
            "page_size": "8",
        }
    )
    url = "https://api.openverse.org/v1/images/?" + params
    try:
        payload = _get_json(url)
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, ValueError):
        return []
    results = payload.get("results") if isinstance(payload, dict) else None
    if not isinstance(results, list):
        return []
    found: list[Candidate] = []
    for item in results:
        if not isinstance(item, dict):
            continue
        code = str(item.get("license") or "")
        version = str(item.get("license_version") or "")
        license_name = f"CC {code} {version}".strip()
        if code in {"cc0", "pdm"}:
            license_name = "CC0" if code == "cc0" else "Public domain"
        file_url = str(item.get("thumbnail") or "")
        if not _allowed_image_host(file_url):
            file_url = ""
        found.append(
            Candidate(
                title=_plain(str(item.get("title") or ""))[:200] or "Openverse image",
                artist=_plain(str(item.get("creator") or item.get("attribution") or ""))[:200]
                or "unknown artist",
                license_name=license_name[:120],
                license_url=str(item.get("license_url") or "")[:500],
                source_page=str(item.get("foreign_landing_url") or item.get("url") or "")[:500],
                file_url=file_url[:1000],
            )
        )
    return found


def _download(candidate: Candidate, dest_dir: Path, guardian: Guardian) -> Path | None:
    decision = guardian.review_navigation(candidate.file_url, resolve=True)
    if not decision.allowed or not _allowed_image_host(candidate.file_url):
        return None
    request = urllib.request.Request(
        candidate.file_url,
        headers={"User-Agent": USER_AGENT, "Accept": "image/jpeg,image/png,image/webp"},
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            final_url = response.geturl()
            if not _allowed_image_host(final_url):
                return None
            kind = (response.headers.get("Content-Type") or "").split(";", 1)[0].strip().lower()
            if kind not in {"image/jpeg", "image/png"}:
                return None
            data = response.read(MAX_BYTES + 1)
    except (urllib.error.URLError, TimeoutError, ValueError):
        return None
    if len(data) < 32 or len(data) > MAX_BYTES:
        return None
    prepared = _prepare_image(data)
    if prepared is None:
        return None
    blob, suffix = prepared
    path = dest_dir / f"reference{suffix}"
    path.write_bytes(blob)
    return path


def _prepare_image(data: bytes) -> tuple[bytes, str] | None:
    """Keep PNG and JPEG files Word can embed. Some Commons JPEGs omit the JFIF header."""

    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return data, ".png"
    if not data.startswith(b"\xff\xd8\xff"):
        return None
    if data[6:10] not in {b"JFIF", b"Exif"}:
        app0 = bytes.fromhex("ffe000104a46494600010100000100010000")
        data = data[:2] + app0 + data[2:]
    return data, ".jpg"


def _get_json(url: str) -> dict:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=20) as response:
        raw = response.read(2_000_000)
    payload = json.loads(raw.decode("utf-8", "replace"))
    if not isinstance(payload, dict):
        raise ValueError("not an object")
    return payload


def _allowed_image_host(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower().rstrip(".")
    if host in {"upload.wikimedia.org", "commons.wikimedia.org", "api.openverse.org"}:
        return True
    return host.endswith(".wikimedia.org") and host != "wikimedia.org"


def _meta(meta: dict, key: str) -> str:
    item = meta.get(key)
    if isinstance(item, dict):
        return str(item.get("value") or "")
    return ""


def _plain(value: str) -> str:
    text = html.unescape(_TAG.sub(" ", value or ""))
    return " ".join(text.split())


def _write_placeholder_png(path: Path) -> None:
    """A grey checkerboard. It is a drawing, not a photo of a room."""

    width, height = 64, 40
    raw = bytearray()
    for y in range(height):
        raw.append(0)
        for x in range(width):
            shade = 176 if ((x // 8) + (y // 8)) % 2 == 0 else 214
            raw.extend((shade, shade, shade))
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    png = b"\x89PNG\r\n\x1a\n" + _chunk(b"IHDR", ihdr) + _chunk(b"IDAT", zlib.compress(bytes(raw))) + _chunk(b"IEND", b"")
    path.write_bytes(png)


def _chunk(tag: bytes, data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
