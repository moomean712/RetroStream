# Windows XP icon asset selection

The project-supplied `Windows XP Icons` directory remains untouched and is not
shipped wholesale. No README, license or attribution file was present in that
directory when this selection was made. Confirm the source pack's redistribution
terms before publishing binaries outside the project.

RetroStream ships small PNG copies in `retrostream/frontend/static/icons`:

| UI function | Supplied source icon |
| --- | --- |
| Dashboard | `WMS Streaming Server.png` |
| Library | `My Music.png` |
| Playlists | `WMP Playlist.png` |
| Add media | `Add.png` |
| Storage | `WMS Cache.png` |
| Settings | `Control Panel.png` |
| System status | `Computer Management.png` |
| Login / setup / logout | `Login Question.png`, `Security - Ok.png`, `Logout.png` |
| Audio / video | `Audio CD.png`, `Generic Video.png` |
| Success / error | `Success.png`, `Security Error.png` |
| Brand mark and favicon | `Windows Media Player 10.png` |

Navigation and status copies are 24 pixels; login/setup also have 48-pixel copies.
The Windows Media Player mark is supplied at 16, 32 and 56 pixels, with a 32-pixel
ICO favicon. They were resized with FFmpeg and retain transparency. Replace or
regenerate only the optimized copies if the source pack changes.
