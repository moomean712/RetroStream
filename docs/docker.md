# Docker deployment

## Beginner setup

Install and start Docker Desktop (Windows/macOS), or Docker Engine plus the Docker
Compose plugin (Linux). Extract the complete RetroStream starter folder, then run:

```sh
./install-docker.sh
```

On Windows PowerShell:

```powershell
powershell -ExecutionPolicy Bypass -File .\install-docker.ps1
```

The policy option applies only to that invocation; it does not weaken the machine's
permanent PowerShell policy. The helper checks Docker, offers a detected LAN IPv4
address, writes `.env`, starts RetroStream, waits for health, and shows the setup URL
and one-time code. If code extraction fails, run `docker compose logs retrostream`.

New installations use TCP **8780** for setup/UI/API/playlists and **8781** for media.
Allow both through the server firewall only from trusted LANs. Do not configure
Internet port forwarding. The address in `.env` must be what retro clients use—not
`localhost`, `127.0.0.1`, a container name, or Docker's private bridge address.

## Everyday commands

Run these in the extracted RetroStream folder:

```sh
docker compose up -d
docker compose down
docker compose ps
docker compose logs -f retrostream
docker compose restart retrostream
```

In order: start, stop, show status, follow logs, and restart. Normal stop/restart
commands preserve all data. Never add `-v` to a normal stop command.

## Updates

Run `./update-docker.sh` on Linux or `.\update-docker.ps1` on Windows. The helper
pulls the current `ghcr.io/moomean712/retrostream` image, recreates the service,
waits for health, and does not delete either named volume. Versioned database
migrations run automatically.

## Backup and restore

Run `./backup-docker.sh` or `.\backup-docker.ps1`. The helper pauses RetroStream
briefly so SQLite and its WAL are consistent, copies `/data` to a timestamped private
folder under `backups/`, then starts the service again. Cache is reproducible and is
omitted by default. Include it with `--include-cache` on Linux or `-IncludeCache` on
Windows.

To restore, stop RetroStream, keep the current backup safe, and copy a selected data
backup into the existing container before restarting:

```sh
docker compose stop retrostream
docker compose cp backups/retrostream-YYYYMMDD-HHMMSS/data/. retrostream:/data
docker compose start retrostream
```

Restore only a backup made by a compatible RetroStream release, then review logs as
migrations run. Backups contain password hashes and sessions; protect them.

## Troubleshooting

- **RetroStream doesn't open:** run `docker compose ps`. It should say healthy.
- **How do I see errors?** Run `docker compose logs retrostream`.
- **My retro PC can't connect:** verify `.env` has the correct LAN IP/name, firewall
  and VLAN rules allow TCP 8780 and 8781, and the client can resolve that name.
- **I changed my server IP:** update `RETROSTREAM_HOSTNAME` in `.env`, then run
  `docker compose up -d --force-recreate retrostream`. Download fresh ASX snapshots.
- **Will updating delete playlists?** No. Normal updates preserve the data and cache.

## Persistence and advanced settings

`retrostream-data` stores SQLite, administrator/session state, settings, playlist
slugs, library data, and the single-instance lock. `retrostream-cache` stores prepared
WMA/WMV files and Deno cache. The container itself is disposable. Compose passes:

- `RETROSTREAM_HOSTNAME`, `RETROSTREAM_WEB_PORT`, `RETROSTREAM_STREAMING_PORT`
- `RETROSTREAM_MAX_CACHE_BYTES`, `RETROSTREAM_RETENTION_DAYS`
- `RETROSTREAM_DEFAULT_AUDIO`, `RETROSTREAM_DEFAULT_VIDEO`
- `RETROSTREAM_MAX_TRANSCODES`, `RETROSTREAM_MAX_STREAMS`

See `.env.example`. Advanced operators can replace named volumes with absolute bind
mounts, but both paths must be writable by UID/GID **10001**. A custom TOML file can
be mounted and selected with `RETROSTREAM_CONFIG`; environment values take precedence.
Keep public web and application ports identical because RetroStream embeds configured
ports in URLs. Reverse proxies must preserve a stable LAN hostname and cannot proxy
only the UI: clients also need the media listener.

The initial published image targets `linux/amd64`. Arm64 should not be claimed until
an arm64 image completes the same media and persistence checks. A version can be
pinned with `RETROSTREAM_IMAGE` without changing Compose layout.

## Port migration

New defaults are 8780/8781. Existing installations with explicit 8080/8081 TOML or
environment values stay on those ports; RetroStream does not rewrite configuration.
Dynamic playlists use current configured ports. Previously downloaded ASX snapshots
keep their old URLs and should be downloaded again after an intentional port change.

## Destructive uninstall

Deleting Docker volumes permanently removes the administrator, library, playlists,
settings, and possibly cached media. Make and verify a backup first. Volume removal is
intentionally excluded from normal stop, update, and troubleshooting instructions.

## Project-owner Docker acceptance checklist

- [ ] Start a fresh Docker installation and complete administrator setup.
- [ ] Import a small YouTube playlist.
- [ ] Prepare Audio, Video Low (Legacy), and Standard/High video.
- [ ] Open Audio ASX on a retro client.
- [ ] Open Video ASX on Windows Me/WMP7 and verify WMV1 Low playback.
- [ ] Confirm generated web/media URLs use the configured LAN host and 8780/8781.
- [ ] Restart the container; confirm administrator, library, and playlists remain.
- [ ] Recreate it with `docker compose up -d --force-recreate`; confirm DB/cache remain.
- [ ] Run the update helper; confirm automatic migration and startup.
- [ ] Re-test an existing permanent playlist URL and cached playback.
- [ ] Verify FFmpeg exposes wmav2/wmv1/wmv2 and ASF, and Deno/yt-dlp run in the image.

## Automated container check

After building and starting, run `sh docker/test-container.sh`. It checks health,
both listeners, runtime dependencies and codec/muxer availability without YouTube.
