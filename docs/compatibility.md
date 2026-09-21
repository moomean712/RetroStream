# Manual XP, WMP and Messenger acceptance checklist

**All real-client results start NOT RUN.** Automated decoding is not a substitute
for this matrix. Copy the table for each tested machine/build and attach the date,
server version, dependency versions and a sanitized log excerpt to the result.

The completed Windows 11 WMP Legacy smoke check and the project owner's reported
VM/Windows XP acceptance are recorded in [validation.md](validation.md). Exact XP
client versions were not supplied, so the per-version matrix below stays unmarked.

| Client | Audio | Video | Seek | Playlist controls | WLM metadata |
| --- | --- | --- | --- | --- | --- |
| Windows XP SP3 / WMP 9 | NOT RUN | NOT RUN | NOT RUN | NOT RUN | NOT RUN |
| Windows XP SP3 / WMP 10 | NOT RUN | NOT RUN | NOT RUN | NOT RUN | NOT RUN |
| Windows XP SP3 / WMP 11 | NOT RUN | NOT RUN | NOT RUN | NOT RUN | NOT RUN |
| Appropriate WLM build + WMP Music Plugin | NOT RUN | NOT RUN | NOT RUN | NOT RUN | NOT RUN |
| Internet Explorer 8 HTML forms | NOT RUN | N/A | N/A | NOT RUN | N/A |

Record XP service pack/build, WMP full version, CPU/RAM, codec changes, WLM
version/plugin name, network path, public hostname, and whether `stream_request`
logs show `wmsp` or `http`. Avoid changing multiple variables between test runs.

## Preparation

- [ ] On a fresh database, obtain the setup code from console/journal and create the administrator.
- [ ] Confirm an invalid setup code fails and setup cannot run again after completion.
- [ ] Log out, verify management pages require login, then log in again.
- [ ] Install with the beginner Docker helper and confirm the container is healthy.
- [ ] Record Python, SQLite, FFmpeg, yt-dlp and Deno versions.
- [ ] Reboot the Docker host and verify automatic startup and the preserved library.
- [ ] Import two permitted short public videos and a public YouTube playlist.
- [ ] Include known structured artist/track/album metadata and non-ASCII text.
- [ ] Import one duplicate and confirm there is still one library object.
- [ ] Create a local playlist of at least three separate entries.
- [ ] Include one unavailable item; verify the error is visible and ASX still opens.
- [ ] Pre-cache Audio Standard and Video Low before testing the initial connection.

## WMP checks (repeat for 9, 10 and 11)

- [ ] File → Open URL accepts the permanent HTTP Audio ASX URL.
- [ ] Download Audio ASX and open the local snapshot; compare its track presentation.
- [ ] Playlist title appears; entries are separate and in the correct order.
- [ ] Track title and artist appear, including escaped/non-ASCII metadata.
- [ ] Duration is plausible and finite; playback isn't treated as endless radio.
- [ ] Play / pause / resume / stop work.
- [ ] Seek forward, backward, to the middle and near the end of every item.
- [ ] Seek again after pausing; verify audio/video synchronization.
- [ ] Disconnect/reconnect or reopen the media after stopping.
- [ ] Next and previous switch individual items.
- [ ] Shuffle changes client playback order without changing the server playlist.
- [ ] Repeat one / repeat all behave according to that WMP version.
- [ ] Rename and reorder the playlist, then reopen the same URL and see changes.
- [ ] Repeat with Video ASX, Low then Standard, and High where supported.
- [ ] On WMP 9+, repeat with Audio and Video WPL and record pre-play track names.
- [ ] Repeat Audio with the 192 kbps profile where practical.
- [ ] Clear one unpinned representation; first request prepares it and later requests reuse it.
- [ ] Record first-use delay, any WMP timeout, and whether pre-caching resolves it.
- [ ] Start a long delivery, run cleanup, and verify the active object survives.
- [ ] Pin the playlist, fill cache past threshold, and verify protected objects survive.
- [ ] Restart the server, reopen the same ASX, and verify cached seek still works.

Do not mark a failed uncached request as passed merely because pre-caching works.
Record the limitation and whether the server's first-use workflow needs changing.

## Windows Live Messenger

- [ ] Locate and enable the installed WMP Messenger Music Plugin, typically under
  Tools → Options → Plug-ins → Background; record the actual name/menu path.
- [ ] Enable Messenger's Show what I'm listening to option where that build offers it.
- [ ] Play a local tagged WMA as a baseline. Record whether Artist – Track is shown.
- [ ] Open RetroStream Audio ASX and compare the same fields with the local baseline.
- [ ] Next/previous updates metadata to the current entry.
- [ ] Pause/stop behavior is recorded (it may vary by WMP/plugin/WLM version).
- [ ] Repeat with Video mode; record whether that plugin publishes video metadata.
- [ ] Document historical service connectivity separately from local plugin behavior.

RetroStream does not implement Messenger integration. If local-file baseline
publishing fails, the server cannot establish whether streaming metadata is the
cause. Preserve raw observed behavior rather than assuming all versions agree.

## Browser and installation

- [ ] Routine Library, Playlist, Storage and Status actions remain on their originating page.
- [ ] Search text, page number and media anchor survive a routine action redirect.
- [ ] Audio quality controls contain only audio choices; Video contains only video choices.
- [ ] Copy URL works in a modern browser; the visible input supports Ctrl+C without JavaScript.
- [ ] Open uses a dynamic permanent playlist; Download remains an unchanged snapshot.
- [ ] In IE8, create/rename/delete a playlist, import URLs and use reorder/remove forms.
- [ ] Long Library, Playlist, Storage and Status lists navigate in 20-item pages.
- [ ] Cache radios clearly distinguish Not cached, Temporary and Permanent.
- [ ] Confirmation is required for playlist deletion, library-track deletion and cache clearing.
- [ ] Deleting a library track removes all membership, cached profiles and play history.
- [ ] Clearing the completed task log preserves queued and running tasks.
- [ ] All essential operations work with JavaScript disabled in a modern browser.
- [ ] Unsupported Host headers and missing CSRF tokens are rejected.
- [ ] Database, cache and configuration survive a backed-up upgrade and rollback drill.
