# Windows XP icon assets and attribution

RetroStream uses selected icons from marchmountain's **Windows XP High Resolution
Icon Pack**. The pack was originally published on
[DeviantArt](https://www.deviantart.com/marchmountain/art/Windows-XP-High-Resolution-Icon-Pack-916042853),
and the creator also published its source files on
[GitHub](https://github.com/marchmountain/-Windows-XP-High-Resolution-Icon-Pack)
under the CC0-1.0 license.

RetroStream includes resized and optimized PNG derivatives in
`retrostream/frontend/static/icons` for interface use. The complete source pack is
not shipped with RetroStream.

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

The CC0 release applies to the icon pack creator's contribution. Recognizable
Microsoft names, logos and trademarks remain the property of their respective
owners. RetroStream is not affiliated with, endorsed by or sponsored by Microsoft.
