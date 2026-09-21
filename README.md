# RetroStream

RetroStream turns modern YouTube media into Windows Media formats that classic
Windows PCs can play across your local network.

```text
YouTube → RetroStream Docker app → Windows Media Player on your LAN
```

It provides a Windows XP-style management page, persistent playlists, permanent
ASX/WPL links, and WMA/WMV preparation using FFmpeg. The Docker app includes
Python, FFmpeg, yt-dlp, Deno, and SQLite; you do not install them separately.

> RetroStream is designed for a trusted home LAN. Do not expose its ports to the
> public Internet.

## Screenshots

Screenshots will be added here. The interface is intentionally styled after the
Windows XP Luna era and remains usable in older browsers.

## What you need

- A computer or NAS that stays on while retro PCs use RetroStream.
- Docker Desktop on Windows/macOS, or Docker Engine with the Docker Compose plugin
  on Linux.
- A retro PC that can reach the Docker computer over the same LAN.
- TCP ports **8780** and **8781** allowed through the Docker computer's firewall.

No Internet port forwarding is required or recommended.

## Step-by-step installation

### 1. Install Docker

**Windows or macOS:** install Docker Desktop from Docker's official website, start
it, and wait until Docker reports that it is running.

**Linux:** install Docker Engine and the Docker Compose plugin using Docker's
instructions for your distribution. Confirm your account can run `docker info`.

RetroStream never installs Docker or makes privileged package-manager changes for you.

### 2. Download RetroStream

On this GitHub page, select **Code → Download ZIP**. Extract the ZIP to a permanent
folder. Do not run the setup helper from inside the ZIP preview.

Advanced users may clone the repository instead:

```sh
git clone https://github.com/moomean712/RetroStream.git
cd RetroStream
```

### 3. Run the setup helper

On Linux or macOS, open a terminal in the extracted `RetroStream` folder and run:

```sh
./install-docker.sh
```

If the extracted file is not executable, use:

```sh
sh install-docker.sh
```

On Windows, open PowerShell in the extracted folder and run:

```powershell
powershell -ExecutionPolicy Bypass -File .\install-docker.ps1
```

That execution-policy option applies only to this one command.

### 4. Confirm the LAN address

The helper detects a likely address and asks:

```text
Detected LAN address: 192.168.1.50

How will your retro PCs reach this server?
[192.168.1.50]:
```

Press Enter if the detected address is correct. Otherwise enter the reserved LAN IP
or DNS name your retro PCs use, such as `retrostream.home.arpa`. Do not enter
`http://`, a port, `localhost`, `127.0.0.1`, or a Docker container name.

The helper then downloads the RetroStream image, starts it, waits for it to become
healthy, and prints the setup address and one-time administrator code.

### 5. Create the administrator

Open the printed address in a modern browser, normally:

```text
http://YOUR-SERVER:8780/setup
```

Enter the setup code printed by the helper and create the administrator account.
The plaintext code is not stored in the database and stops working after setup.

If the helper could not display the code, run:

```sh
docker compose logs retrostream
```

### 6. Add and play media

1. Sign in to RetroStream.
2. Create a playlist or open **Add Media**.
3. Paste a YouTube video or playlist URL.
4. Wait for the import job to finish under **System Status**.
5. Optionally prepare Audio or Video in advance.
6. Open or download the playlist's ASX link.
7. Open that ASX file in Windows Media Player on the retro PC.

Use **Low (Legacy)** video for the oldest clients; it uses WMV1. Standard and High
use WMV2. Audio uses WMA/WMAv2.

## Your data is persistent

RetroStream stores important state separately from the replaceable app:

- `retrostream-data`: administrator, sessions, settings, library, playlists, slugs,
  and SQLite database.
- `retrostream-cache`: prepared WMA/WMV files and temporary media work.

Normal stops, restarts, and updates do not remove these stores.

## Everyday commands

Run commands from the extracted RetroStream folder:

```sh
# Start
docker compose up -d

# Stop
docker compose down

# Show status
docker compose ps

# Follow logs (Ctrl+C stops watching; it does not stop RetroStream)
docker compose logs -f retrostream

# Restart
docker compose restart retrostream
```

Do not add `-v` to normal stop or update commands. Removing volumes deletes data.

## Update RetroStream

Linux/macOS:

```sh
./update-docker.sh
```

Windows PowerShell:

```powershell
.\update-docker.ps1
```

The helper downloads the latest image, recreates the app, runs database migrations,
waits for health, and preserves both data stores.

## Back up and restore

Create a consistent timestamped backup of important `/data` state:

```sh
./backup-docker.sh
```

Windows PowerShell:

```powershell
.\backup-docker.ps1
```

The helper pauses RetroStream briefly while copying the SQLite state, then starts it
again. Add `--include-cache` on Linux/macOS or `-IncludeCache` on Windows to include
prepared media. Backups are written below `backups/` and contain sensitive account
and session state, so keep them private.

To restore a compatible backup:

```sh
docker compose stop retrostream
docker compose cp backups/retrostream-YYYYMMDD-HHMMSS/data/. retrostream:/data
docker compose start retrostream
docker compose logs retrostream
```

Keep a copy of the current state before restoring an older backup.

## Troubleshooting

### RetroStream does not open

Run `docker compose ps`. The service should show `healthy`. Then inspect
`docker compose logs retrostream`.

### My retro PC cannot connect

Check all of the following:

- `RETROSTREAM_HOSTNAME` in `.env` is the address used by the retro PC.
- The retro PC can resolve that name or reach that IP.
- The server firewall allows trusted-LAN TCP traffic to **8780** and **8781**.
- Wi-Fi isolation, guest networks, or VLAN rules are not blocking the connection.
- The generated ASX media references use the LAN address and port 8781.

### My server IP changed

Edit `RETROSTREAM_HOSTNAME` in `.env`, then run:

```sh
docker compose up -d --force-recreate retrostream
```

Dynamic playlist links immediately use the new address. Previously downloaded ASX
files still contain the old address and must be downloaded again.

### Will updating delete playlists?

No. The update helpers preserve the Docker data and cache stores.

### Docker says the image is unauthorized or not found

The GitHub Container Registry package must be public and the `latest` workflow must
have completed successfully. Check this repository's **Actions** and **Packages** pages.

## Configuration

The installer creates `.env`. Most users only need:

```dotenv
RETROSTREAM_HOSTNAME=192.168.1.50
RETROSTREAM_WEB_PORT=8780
RETROSTREAM_STREAMING_PORT=8781
```

Optional settings are documented in [.env.example](.env.example):

- cache size and retention
- default audio/video quality
- maximum simultaneous transcodes and streams
- a pinned image version

New installations use ports 8780/8781. Existing explicit 8080/8081 settings remain
valid and are not silently rewritten by the installer.

## Build locally for development

Normal users should use the published image. Developers can build the current source:

```sh
docker compose -f compose.yaml -f compose.build.yaml up -d --build
```

Run the Python test suite with:

```sh
python -m pip install -e '.[test]'
python -m pytest -q
python -m ruff check retrostream tests
python -m ruff format --check retrostream tests
```

The GitHub workflow builds the image, starts Compose, tests health and both listeners,
checks FFmpeg WMAv2/WMV1/WMV2 and ASF support, performs synthetic media encodes, tests
volume persistence across recreation, and publishes successful `main` builds to:

```text
ghcr.io/moomean712/retrostream:latest
```

## Security and scope

- One administrator account; this is not a multi-user hosted service.
- Intended for trusted LAN use only.
- No DRM bypass and no public Internet exposure.
- No nginx, database server, Redis, queue service, or supervisor in the image.
- One non-root RetroStream process; persistent writes are limited to `/data` and `/cache`.

## License

RetroStream source is provided under the [MIT License](LICENSE). FFmpeg, yt-dlp,
Deno, Python dependencies, and supplied visual assets retain their own licenses.
