from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin, urlparse

SKIP_TEXT_TAGS = {"script", "style", "noscript", "template", "svg"}
SKIP_SKELETON_TAGS = {
    "script",
    "style",
    "noscript",
    "template",
    "meta",
    "link",
    "svg",
    "path",
    "source",
}
ASSET_ATTRIBUTES = {
    "img": "src",
    "script": "src",
    "source": "src",
    "link": "href",
}
EXACT_FIELDS = (
    "title",
    "visible_text_sha256",
    "internal_links_sha256",
    "tag_skeleton_sha256",
    "asset_paths_sha256",
)


def _normalize_space(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _normalized_url_path(value: str, host: str) -> tuple[str, str] | None:
    value = value.strip()
    if not value or value.startswith(("#", "mailto:", "tel:", "javascript:")):
        return None
    absolute = urljoin(f"https://{host}/", value)
    parsed = urlparse(absolute)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return None
    path = parsed.path or "/"
    return parsed.hostname.lower(), path


class StructuralHTMLParser(HTMLParser):
    def __init__(self, host: str) -> None:
        super().__init__(convert_charrefs=True)
        self.host = host.lower()
        self.title_parts: list[str] = []
        self.visible_parts: list[str] = []
        self.internal_links: set[str] = set()
        self.asset_paths: set[str] = set()
        self.tag_skeleton: list[str] = []
        self._skip_text_depth = 0
        self._in_title = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        attributes = {key.lower(): value for key, value in attrs if value is not None}

        if tag == "title":
            self._in_title = True

        if tag in SKIP_TEXT_TAGS:
            self._skip_text_depth += 1

        if tag not in SKIP_SKELETON_TAGS:
            self.tag_skeleton.append(f"<{tag}>")

        if tag == "a" and (href := attributes.get("href")):
            normalized = _normalized_url_path(href, self.host)
            if normalized and normalized[0] == self.host:
                self.internal_links.add(normalized[1])

        asset_attribute = ASSET_ATTRIBUTES.get(tag)
        if asset_attribute and (asset := attributes.get(asset_attribute)):
            normalized = _normalized_url_path(asset, self.host)
            if normalized:
                asset_host, path = normalized
                self.asset_paths.add(f"{asset_host}{path}")

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag == "title":
            self._in_title = False

        if tag not in SKIP_SKELETON_TAGS:
            self.tag_skeleton.append(f"</{tag}>")

        if tag in SKIP_TEXT_TAGS and self._skip_text_depth > 0:
            self._skip_text_depth -= 1

    def handle_data(self, data: str) -> None:
        normalized = _normalize_space(data)
        if not normalized:
            return
        if self._in_title:
            self.title_parts.append(normalized)
            return
        if self._skip_text_depth == 0:
            self.visible_parts.append(normalized)


def fingerprint_bytes(raw_html: bytes, host: str) -> dict[str, object]:
    text = raw_html.decode("utf-8", errors="replace")
    parser = StructuralHTMLParser(host)
    parser.feed(text)
    parser.close()

    title = _normalize_space(" ".join(parser.title_parts))
    visible_text = _normalize_space(" ".join(parser.visible_parts))
    internal_links = sorted(parser.internal_links)
    assets = sorted(parser.asset_paths)
    skeleton = "\n".join(parser.tag_skeleton)

    return {
        "version": 1,
        "title": title,
        "visible_text_sha256": _sha256(visible_text),
        "internal_links_sha256": _sha256("\n".join(internal_links)),
        "tag_skeleton_sha256": _sha256(skeleton),
        "asset_paths_sha256": _sha256("\n".join(assets)),
        "html_bytes": len(raw_html),
        "visible_text_chars": len(visible_text),
        "internal_link_count": len(internal_links),
        "tag_count": len(parser.tag_skeleton),
        "asset_count": len(assets),
    }


def fingerprint_file(path: str | Path, host: str) -> dict[str, object]:
    return fingerprint_bytes(Path(path).read_bytes(), host)


def compare_fingerprints(
    baseline: dict[str, object],
    current: dict[str, object],
    max_byte_delta_pct: float = 3.0,
) -> list[str]:
    errors: list[str] = []
    if baseline.get("version") != current.get("version"):
        errors.append("fingerprint version changed")

    for field in EXACT_FIELDS:
        if baseline.get(field) != current.get(field):
            errors.append(f"{field} changed")

    baseline_bytes = int(baseline.get("html_bytes", 0))
    current_bytes = int(current.get("html_bytes", 0))
    if baseline_bytes <= 0 or current_bytes <= 0:
        errors.append("invalid HTML byte count")
    else:
        delta_pct = abs(current_bytes - baseline_bytes) * 100 / baseline_bytes
        if delta_pct > max_byte_delta_pct:
            errors.append(f"html_bytes changed by {delta_pct:.2f}% (allowed {max_byte_delta_pct:.2f}%)")

    return errors


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Stable structural HTML fingerprint")
    subparsers = parser.add_subparsers(dest="command", required=True)

    fingerprint = subparsers.add_parser("fingerprint")
    fingerprint.add_argument("path")
    fingerprint.add_argument("--host", required=True)

    compare = subparsers.add_parser("compare")
    compare.add_argument("path")
    compare.add_argument("--host", required=True)
    compare.add_argument("--baseline-json", required=True)
    compare.add_argument("--max-byte-delta-pct", type=float, default=3.0)

    return parser


def main() -> int:
    args = _build_parser().parse_args()
    current = fingerprint_file(args.path, args.host)

    if args.command == "fingerprint":
        print(json.dumps(current, ensure_ascii=False, separators=(",", ":")))
        return 0

    baseline = json.loads(args.baseline_json)
    errors = compare_fingerprints(
        baseline,
        current,
        max_byte_delta_pct=args.max_byte_delta_pct,
    )
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1

    print(json.dumps({"ok": True, "current": current}, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
