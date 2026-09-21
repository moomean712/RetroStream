# Validation report — 20 September 2026

This is a working v1 implementation with recorded Windows 11 client verification
and owner-reported Debian 13 VM/Windows XP acceptance of the earlier v1 build.
Exact retro client versions and external logs are not available here, so this is
not per-version certification. The administrator, WPL and revised UI refinement
described below has automated and browser coverage; its WMP pass is intentionally
deferred for a joint test with the owner.

## Automated results

- Python 3.12 on Windows 11; FFmpeg 7.1; yt-dlp 2026.8.19.
- `python -m pytest -q`: **45 passed**, two dependency deprecation warnings.
- `python -m ruff check retrostream tests`: passed.
- Tests cover imports and normalization, persistent playlists and stable slugs,
  job deduplication/failure recovery, cache generation synchronization, pinning,
  cleanup, startup recovery, first-run administrator setup, password/session
  handling, CSRF/Host protection, safe redirects, forms/API, WPL, snapshot versus
  permanent playlists, friendly media aliases, full library deletion, temporary
  versus permanent cache clearing, 20-row pagination, task-log clearing, and byte ranges.
- All five encoding profiles were generated and their ASF tags inspected.
- An independent FFmpeg MMSH client decoded audio and video through real TCP
  connections, including time-based seeking.

## Live source and browser checks

The public short video `jNQXAC9IVRw` (Me at the zoo) was retrieved with real yt-dlp,
using Node as its JavaScript runtime, and converted to Audio Standard and Video
Standard. This confirms that source at test time; restricted media and other
YouTube playlists were not covered by this live check. Automated import tests
use a deterministic extractor fixture.

The revised login, dashboard, Library, media detail and playlist pages were inspected
in the Codex Chromium browser at 1024x768. The visual pass verified the Windows
Media Player masthead, XP sidebar modules, compact media rows, cache radios and
20-item navigation. This is not an IE8 browser acceptance result.

## Windows 11 WMP Legacy

Tested over loopback with three cached entries: two synthetic 90-second clips
with distinct titles and structured tags, and the live YouTube conversion above.
The observed player HTTP user agent was version **12.0.26100.9278**.

| Check | Observed result |
| --- | --- |
| Permanent Audio ASX URL | Accepted; audio playback position advanced |
| Audio metadata | Track title, album and album artist visible |
| Pause/resume | Paused at 00:38, resumed successfully |
| Audio seek | Sought from 00:38 to 01:02 while paused, resumed past 01:11 |
| Next/previous | Track 1 → Track 2 → Track 1, with updated title and playback |
| Shuffle/repeat | Both controls enabled and toggled; randomized order not statistically verified |
| Permanent Video ASX URL | Accepted; moving test pattern rendered |
| Video seek | Backward seek from about 01:05 to about 00:20; playback continued |
| Next video | Track 2 title and advancing position observed |
| Transport | Ordinary ASF HTTP delivery with `206` byte-range responses |

The playlist appears as a single nested playlist row in WMP's list pane; its
individual entries still advance through Next/Previous. This test does not
establish how every older WMP version presents ASX entries.

Two compatibility defects were discovered and fixed during actual player tests:

1. ASX must start with `<ASX`, without an XML declaration or BOM. The generated
   document now includes explicit UTF-8 and AllowShuffle parameters.
2. NSPlayer identifies both ordinary HTTP file requests and MMSH negotiations.
   User-agent detection alone returned framed headers to byte-range requests.
   Negotiation pragma tokens now select MMSH; file requests get actual ASF bytes.

Regression assertions cover both defects. WMP Legacy used the HTTP path, so the
MMSH evidence here comes from FFmpeg, not from WMP.

## Windows Me / Windows Media Player 7 owner test

On 21 September 2026, the project owner tested a RetroStream Video ASX playlist
on Windows Me with Windows Media Player 7. The original Video Low representation
used WMV2: its WMA audio played, but the video remained black. Replacing only that
cached representation with a WMV1 encode, while keeping the same playlist, media
URL, streaming path, client and installation, produced working audio and video.
Video Low now uses WMV1 (Windows Media Video 7) and is labeled **Low (Legacy)**.
This result applies to the tested environment; it is not a guarantee for every
Windows 98/Me or Windows Media Player configuration.

## Owner acceptance and remaining detail

On 20 September 2026, the project owner reported that the earlier v1 build was
deployed successfully on Debian 13 with Python 3.13, SQLite 3.46, FFmpeg 7.1,
Deno 2.9 and a 2026 yt-dlp release, and that their full test run including a
Windows XP system passed. That acceptance is recorded as owner-reported because
the exact XP service pack, WMP/WLM versions, commands and sanitized logs were not
supplied to this workspace. Add those details to the matrix in
[the full acceptance checklist](compatibility.md) if per-version certification
or reproducible release evidence is needed later.

The isolated Windows test database, cached media, request diagnostics and local
runtime paths are development artifacts and are excluded from release packages.
