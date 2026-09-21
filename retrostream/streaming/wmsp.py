"""MS-WMSP Describe/Play framing for individual fixed-packet ASF VOD objects."""

import re
import struct

from .asf import ASF


def pragmas(values: list[str]) -> dict[str, str]:
    result = {}
    for value in values:
        # FFmpeg's MMSH client omits a CRLF before Connection on its Play request.
        # Tolerate this exact legacy spelling without loosening numeric validation.
        value = re.sub(r"(?<=\d)Connection:\s*Close$", "", value, flags=re.IGNORECASE)
        for match in re.finditer(r'([\w-]+)\s*=\s*("[^"]*"|[^,\s]+)', value):
            result[match[1].lower()] = match[2].strip('"')
    return result


def frame(kind: bytes, payload: bytes, location: int = 0, flags: int = 0) -> bytes:
    length = len(payload) + 8
    if length > 65535:
        raise ValueError("MMS data packet too large")
    return b"$" + kind + struct.pack("<HIBBH", length, location, 0, flags, length) + payload


def header_packets(asf: ASF) -> bytes:
    pieces = [asf.header[n : n + 65527] for n in range(0, len(asf.header), 65527)]
    return b"".join(
        frame(b"H", part, n, (4 if n == 0 else 0) | (8 if n == len(pieces) - 1 else 0))
        for n, part in enumerate(pieces)
    )


def play_packets(asf: ASF, start: int):
    yield header_packets(asf)
    with asf.path.open("rb") as file:
        for sequence, number in enumerate(range(start, asf.packet_count)):
            yield frame(b"D", asf.packet(file, number), number, sequence % 256)
    # Reason 0 means this VOD object has ended. The client owns playlist advance.
    yield b"$E" + struct.pack("<HI", 4, 0)
