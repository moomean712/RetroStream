from xml.etree.ElementTree import Element, SubElement, tostring


def generate(playlist: dict, mode: str, base_url: str) -> bytes:
    if mode not in ("audio", "video"):
        raise ValueError("Unknown playback mode")
    root = Element("ASX", {"version": "3.0"})
    SubElement(root, "PARAM", {"NAME": "Encoding", "VALUE": "utf-8"})
    SubElement(root, "PARAM", {"NAME": "AllowShuffle", "VALUE": "Yes"})
    SubElement(root, "TITLE").text = playlist["name"]
    for media in playlist["items"]:
        if media.get("error"):
            continue
        entry = SubElement(root, "ENTRY")
        SubElement(entry, "TITLE").text = media["title"]
        SubElement(entry, "AUTHOR").text = media.get("artist") or ""
        for field, tag in (
            ("album", "WM/AlbumTitle"),
            ("album_artist", "WM/AlbumArtist"),
            ("genre", "WM/Genre"),
            ("year", "WM/Year"),
            ("track_number", "WM/TrackNumber"),
        ):
            if media.get(field):
                SubElement(entry, "PARAM", {"NAME": tag, "VALUE": str(media[field])})
        SubElement(entry, "REF", {"HREF": f"{base_url}/media/{media['id']}/{mode}"})
    # WMP requires the first four bytes to be <ASX, not an XML declaration/BOM.
    return tostring(root, encoding="utf-8", xml_declaration=False)
