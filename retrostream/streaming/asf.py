"""Read the fixed packet ASF variant produced by our FFmpeg profiles.

All offsets are bounded. This is intentionally not a general ASF demuxer.
"""

import struct
import uuid
from dataclasses import dataclass, field
from pathlib import Path


def guid(value: str) -> bytes:
    return uuid.UUID(value).bytes_le


HEADER = guid("75b22630-668e-11cf-a6d9-00aa0062ce6c")
DATA = guid("75b22636-668e-11cf-a6d9-00aa0062ce6c")
FILE_PROPERTIES = guid("8cabdca1-a947-11cf-8ee4-00c00c205365")
SIMPLE_INDEX = guid("33000890-e5b1-11cf-89f4-00a0c90349cb")


@dataclass
class ASF:
    path: Path
    header: bytes
    packet_size: int
    packet_count: int
    duration_ms: int
    preroll_ms: int = 0
    index_interval_ms: int = 0
    index: list[int] = field(default_factory=list)

    @classmethod
    def read(cls, path: Path):
        size = path.stat().st_size
        with path.open("rb") as file:
            start = file.read(30)
            if len(start) != 30 or start[:16] != HEADER:
                raise ValueError("Invalid ASF header")
            header_size = struct.unpack_from("<Q", start, 16)[0]
            if not 30 <= header_size <= min(size - 50, 4 * 1024**2):
                raise ValueError("Invalid ASF header length")
            file.seek(0)
            header = file.read(header_size + 50)
            position, props = 30, None
            while position < header_size:
                if position + 24 > header_size:
                    raise ValueError("Truncated ASF object")
                length = struct.unpack_from("<Q", header, position + 16)[0]
                if length < 24 or position + length > header_size:
                    raise ValueError("Invalid ASF object size")
                if header[position : position + 16] == FILE_PROPERTIES:
                    props = header[position : position + length]
                position += length
            if not props or len(props) < 104 or header[header_size : header_size + 16] != DATA:
                raise ValueError("ASF properties or data object missing")
            minimum, packet_size = struct.unpack_from("<II", props, 92)
            count = struct.unpack_from("<Q", props, 56)[0]
            duration = struct.unpack_from("<Q", props, 64)[0] // 10000
            preroll = struct.unpack_from("<Q", props, 80)[0]
            if minimum != packet_size or not 1 <= packet_size <= 65527 or not count:
                raise ValueError("Only complete fixed-size ASF packets are supported")
            data_end = header_size + 50 + count * packet_size
            if data_end > size:
                raise ValueError("Incomplete ASF media")
            result = cls(path, header, packet_size, count, max(0, duration - preroll), preroll)
            file.seek(data_end)
            while file.tell() + 24 <= size:
                position = file.tell()
                obj = file.read(24)
                length = struct.unpack_from("<Q", obj, 16)[0]
                if length < 24 or position + length > size:
                    raise ValueError("Invalid trailing ASF object")
                if obj[:16] == SIMPLE_INDEX and length >= 56:
                    raw = file.read(32)
                    interval = struct.unpack_from("<Q", raw, 16)[0] // 10000
                    entries = struct.unpack_from("<I", raw, 28)[0]
                    if entries > (length - 56) // 6 or entries > 2_000_000 or not interval:
                        raise ValueError("Invalid ASF seek index")
                    result.index_interval_ms = interval
                    result.index = [struct.unpack("<IH", file.read(6))[0] for _ in range(entries)]
                    if any(n >= count for n in result.index):
                        raise ValueError("Seek index exceeds ASF data")
                file.seek(position + length)
            return result

    def packet(self, file, number: int) -> bytes:
        file.seek(len(self.header) + number * self.packet_size)
        data = file.read(self.packet_size)
        if len(data) != self.packet_size:
            raise ValueError("Truncated ASF packet")
        return data

    @staticmethod
    def send_time(packet: bytes) -> int:
        offset = 0
        if packet[0] & 0x80:
            offset = 1 + (packet[0] & 0x0F)
        flags = packet[offset]
        sizes = (0, 1, 2, 4)
        offset += 2 + sizes[(flags >> 5) & 3] + sizes[(flags >> 1) & 3] + sizes[(flags >> 3) & 3]
        return struct.unpack_from("<I", packet, offset)[0]

    def seek_packet(self, milliseconds: int) -> int:
        if milliseconds <= 0:
            return 0
        if milliseconds >= self.duration_ms:
            return self.packet_count
        if self.index:
            return self.index[
                min((milliseconds + self.preroll_ms) // self.index_interval_ms, len(self.index) - 1)
            ]
        # Audio packets can contain fragmented objects: rewind a small preroll.
        target = max(0, milliseconds - 2000)
        lo, hi = 0, self.packet_count
        with self.path.open("rb") as file:
            while lo < hi:
                middle = (lo + hi) // 2
                if self.send_time(self.packet(file, middle)) <= target:
                    lo = middle + 1
                else:
                    hi = middle
        return max(0, lo - 1)
