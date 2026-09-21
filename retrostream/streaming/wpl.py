"""Optional WMP 9+ playlist output with cosmetic media filenames."""

import re
import unicodedata
from urllib.parse import quote
from xml.etree.ElementTree import Element, SubElement, tostring


def friendly_filename(media: dict, mode: str) -> str:
    title = media.get("title") or "media"
    artist = media.get("artist")
    label = f"{artist} - {title}" if artist else title
    label = unicodedata.normalize("NFKD", label).encode("ascii", "ignore").decode("ascii")
    label = re.sub(r"[^A-Za-z0-9 ._-]+", "", label).strip(" .")[:80] or "media"
    return label + (".wma" if mode == "audio" else ".wmv")


def media_url(media: dict, mode: str, base_url: str) -> str:
    return f"{base_url}/media/{media['id']}/{mode}/{quote(friendly_filename(media, mode))}"


def generate(playlist: dict, mode: str, base_url: str) -> bytes:
    if mode not in ("audio", "video"):
        raise ValueError("Unknown playback mode")
    root = Element("smil")
    head = SubElement(root, "head")
    SubElement(head, "meta", {"name": "Generator", "content": "RetroStream 0.1"})
    SubElement(head, "title").text = playlist["name"]
    sequence = SubElement(SubElement(root, "body"), "seq")
    for media in playlist["items"]:
        if not media.get("error"):
            SubElement(sequence, "media", {"src": media_url(media, mode, base_url)})
    return b'<?wpl version="1.0"?>\r\n' + tostring(root, encoding="utf-8", xml_declaration=False)
