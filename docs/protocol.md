# Windows Media delivery

## Implemented boundary

`streaming/asx.py` builds escaped ASX 3.0 XML. The first bytes are `<ASX`, without
an XML declaration or BOM. PARAM elements declare UTF-8 and enable client shuffle.
Each item is a separate entry and
references ordinary `http://` media URLs on the streaming port. `mms://` is not
advertised: no native MMSP TCP/UDP service runs on port 1755. Explicit HTTP avoids
depending on a particular WMP version's MMS protocol fallback negotiation.

ASX remains the primary compatibility format. `streaming/wpl.py` additionally
generates WPL for WMP 9 and newer. WPL media entries use cosmetic filenames such
as `/media/{id}/audio/Artist%20-%20Title.wma`; the immutable ID and mode still
perform lookup, and the original `/media/{id}/audio` route remains valid. A
`?download=1` playlist response adds Content-Disposition. Its bytes are a snapshot;
the permanent URL is dynamic when fetched again.

`streaming/http.py` selects a transport from Windows Media request headers.
Ordinary clients receive full ASF files or one byte range, with HEAD, Content-Length,
ETag, If-Range and 416 handling. A completed seekable file is generated before any
successful stream response. The first cache miss waits asynchronously on a shared
job; a client may time out before the server's preparation timeout. Pre-caching is
the recommended initial test workflow.

Requests with Windows Media negotiation pragma tokens use the MMSH adapter.
The NSPlayer user agent alone does not select MMSH: WMP also uses it for ordinary
ASF downloads and byte-range requests, which must receive unframed file bytes.

- Describe returns `application/vnd.ms.wms-hdr.asfv1`, Content-Length, and $H data.
- Play (`xPlayStrm=1`) returns `application/x-mms-framed`, $H, individual $D packets,
  then $E end-of-object. The adapter uses finite Content-Length and closes the connection.
- $H contains the ASF Header Object plus the first 50 bytes of the Data Object.
  Large headers are fragmented with first/last flags.
- $D location numbers refer to original ASF packet numbers; flags count transmitted
  packets modulo 256. Playback never concatenates a playlist into one object.
- `stream-time` selects an indexed packet. Video lookup accounts for FFmpeg's ASF
  preroll in its simple index; audio uses bounded packet-time search with overlap.
- Pause/stop can end delivery; resume/seek opens another Play request at a time
  position. No persistent client identity or server-owned playback cursor is needed.
- Duration and tags come from the completed ASF header. Minimal seekable features
  are advertised; no packet-pair, stride/trick-play, fastcache, or server playlists.
- The response's legacy Cougar identifier enables legacy MMSH client behavior;
  this does not claim to be Microsoft's server implementation.

Unsupported: native MMSP, RTSP, multicast, live media, predictive server playlists,
multi-language/bitrate stream switching, arbitrary ASF variants and variable packet
sizes. The supplied profiles contain one audio stream and optionally one video
stream, both delivered. Unused optional negotiation tokens are ignored. Explicit
pipeline/server-playlist requests are rejected. Byte-offset-only MMSH reconnection
is not implemented; clients must send stream-time for repositioning. These limits
must be checked against the exact target WMP builds before calling v1 stable.

FFmpeg 7.1's MMSH client sends `stream-time=0Connection: Close` in one pragma due
to a missing CRLF. The parser tolerates that exact suffix, with a regression test.
Other malformed time values remain errors.

## Metadata and unavailable entries

Structured track/artist/album fields take precedence over title/uploader. ASF tags
include Title, Author, WM/AlbumTitle, WM/AlbumArtist, WM/Genre, WM/Year and
WM/TrackNumber. Year is set explicitly because generic FFmpeg `date` does not
reliably become WM/Year. Tests inspect the actual output with Mutagen.

ASX includes TITLE, AUTHOR and corresponding WM parameters. A media item marked
unavailable by metadata extraction stays in the library and local playlist, but is
omitted from ASX until **Retry metadata** succeeds. A later download failure is
recorded per representation; other playlist entries remain independently usable.
Cached tags are a snapshot. Refreshing metadata does not rewrite an actively
served file; regenerate the representation to update its embedded tags.

## Research sources

ASX recognition and shuffle behavior follow Microsoft's
[metafile construction rules](https://learn.microsoft.com/en-us/previous-versions/windows/desktop/wmp/creating-metafile-playlists)
and [PARAM reference](https://learn.microsoft.com/en-us/windows/win32/wmp/param-element).

Implementation was derived from the published wire formats and validated against
an independent client; it does not copy an FFmpeg server implementation.

- [Microsoft MS-WMSP Describe](https://learn.microsoft.com/en-us/openspecs/windows_protocols/ms-wmsp/3929a89a-7b1c-43e7-8783-8b6ec304ba0b)
- [Microsoft MS-WMSP Play](https://learn.microsoft.com/en-us/openspecs/windows_protocols/ms-wmsp/4423fe2a-19a4-4919-a95a-7d2305092573)
- [Microsoft $H packet](https://learn.microsoft.com/en-us/openspecs/windows_protocols/ms-wmsp/daa83313-16ab-42cb-ac53-ba7e59956095)
- [Microsoft MMS packet fields](https://learn.microsoft.com/en-us/openspecs/windows_protocols/ms-wmsp/c4246f48-23ca-4c6e-90e9-bf33757c72e2)
- [Microsoft framing](https://learn.microsoft.com/en-us/openspecs/windows_protocols/ms-wmsp/de35c9d0-4798-459b-85a0-578ccd58b1f4)
- [FFmpeg MMSH client source](https://github.com/FFmpeg/FFmpeg/blob/master/libavformat/mmsh.c)
- [FFmpeg ASF muxer](https://github.com/FFmpeg/FFmpeg/blob/master/libavformat/asfenc.c)
- [FFmpeg ASF formats](https://ffmpeg.org/ffmpeg-formats.html#asf_002c-asf_005fstream)

See [compatibility checklist](compatibility.md) for the real-client acceptance gate.
