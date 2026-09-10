# Telegram Large Video Clipper Bot

Telegram bot that receives large forwarded videos and joins them into one final video using FFmpeg.

## Features

- Forward videos directly from Telegram
- Multiple videos supported
- Preserve received order
- `/done`
- `/clear`
- `/status`
- FFmpeg processing
- H.264 output
- AAC audio
- Automatic video normalization
- Different resolutions supported
- Different FPS supported
- Different audio formats handled
- Telegram Local Bot API
- Large file downloads
- Automatic temporary file cleanup

---

# Repository

```text
TG-Video-Clipper/

├── bot.py
├── requirements.txt
├── Dockerfile
├── README.md
├── .gitignore

└── .github/
    └── workflows/
        └── run-bot.yml
