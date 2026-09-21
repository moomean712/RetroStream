# Contributing

Start with README.md and docs/architecture.md. Use Python 3.11+, a virtual
environment and the test extra. Run pytest, Ruff checks and formatting before
submitting a change. Tests must not require private media, YouTube cookies or
access to a maintainer's LAN. Keep source inputs restricted to supported YouTube
URLs and pass subprocess argument lists, never shell commands.

Separate protocol behavior from web/library/cache behavior. Add wire-format tests
and independent-decoder tests for protocol changes. Record actual WMP results in
docs/compatibility.md; don't convert NOT RUN to PASS based on modern-player behavior.
Cache changes must preserve library metadata, reference pins and active-stream
protection. Add a new numbered SQL migration for schema changes; never edit an
already released migration to change an existing installation's schema.

Keep the service single-process and LAN-first. Docker and public hosting are not
part of this release. Essential browser workflows must remain plain HTML forms.
Generated-media fixtures should be synthetic or freely redistributable.

An issue report should include OS/Python/FFmpeg/yt-dlp/WMP versions, relevant safe
job messages, reproduction steps, expected behavior and observed behavior. Remove
personal paths, addresses, cookies and signed URLs before sharing logs. The MIT
license is the proposed project license; maintainers should confirm licensing and
dependency notices before publishing a first release.
