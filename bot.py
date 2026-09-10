import asyncio
import logging
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
if not TOKEN:
    raise RuntimeError("TELEGRAM_BOT_TOKEN secret is missing.")

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(message)s",
    level=logging.INFO,
)
log = logging.getLogger("video-clipper")

# Per-chat queue: each chat can collect videos independently.
queues: dict[int, list[Path]] = {}
locks: dict[int, asyncio.Lock] = {}


def get_lock(chat_id: int) -> asyncio.Lock:
    if chat_id not in locks:
        locks[chat_id] = asyncio.Lock()
    return locks[chat_id]


def run_ffmpeg_concat(inputs: list[Path], output: Path) -> None:
    """
    Robust join: re-encodes each input to the same H.264/AAC format,
    then concatenates them. This is slower than stream-copy but handles
    different resolutions/FPS/audio layouts much more reliably.
    """
    work = output.parent / "normalized"
    work.mkdir(parents=True, exist_ok=True)

    normalized = []
    for i, src in enumerate(inputs):
        dst = work / f"part_{i:03d}.mp4"
        cmd = [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-i", str(src),
            "-map", "0:v:0",
            "-map", "0:a:0?",
            "-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2,format=yuv420p",
            "-r", "30",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
            "-c:a", "aac", "-b:a", "128k",
            "-ar", "48000",
            "-movflags", "+faststart",
            str(dst),
        ]
        subprocess.run(cmd, check=True)
        normalized.append(dst)

    concat_file = work / "concat.txt"
    with concat_file.open("w", encoding="utf-8") as f:
        for p in normalized:
            f.write(f"file '{p.resolve().as_posix().replace(\"'\", \"'\\\\''\")}'\n")

    cmd = [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-f", "concat", "-safe", "0",
        "-i", str(concat_file),
        "-c", "copy",
        "-movflags", "+faststart",
        str(output),
    ]
    subprocess.run(cmd, check=True)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🎬 Video Clipper Bot ready!\n\n"
        "Send/forward Video 1, then Video 2.\n"
        "Use /done to join them.\n\n"
        "For more than 2 videos, send all of them in order and use /done.\n"
        "/clear — clear the current queue\n"
        "/status — show queued videos"
    )


async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    q = queues.get(chat_id, [])
    await update.message.reply_text(f"📦 Queued videos: {len(q)}")


async def clear(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    q = queues.pop(chat_id, [])
    for p in q:
        try:
            shutil.rmtree(p.parent, ignore_errors=True)
        except Exception:
            pass
    await update.message.reply_text("🗑️ Queue cleared.")


async def receive_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message
    chat_id = update.effective_chat.id

    # Telegram's standard Bot API download limit is about 20 MB.
    # This code intentionally reports a clear error instead of silently failing.
    tg_file = None
    filename = "video.mp4"

    if message.video:
        tg_file = await message.video.get_file()
        filename = message.video.file_name or "video.mp4"
    elif message.document and (message.document.mime_type or "").startswith("video/"):
        tg_file = await message.document.get_file()
        filename = message.document.file_name or "video.mp4"
    else:
        return

    async with get_lock(chat_id):
        base = Path(tempfile.mkdtemp(prefix="tgclip_"))
        safe_name = Path(filename).name
        if not safe_name.lower().endswith((".mp4", ".mkv", ".mov", ".webm", ".avi", ".m4v")):
            safe_name += ".mp4"
        path = base / safe_name

        try:
            await tg_file.download_to_drive(custom_path=str(path))
        except Exception as e:
            shutil.rmtree(base, ignore_errors=True)
            await message.reply_text(
                "❌ I couldn't download that video.\n"
                "The normal Telegram Bot API has a ~20 MB file-download limit. "
                "For larger videos, this repository needs a Telegram Local Bot API "
                "server or a user-client based version.\n\n"
                f"Error: {e}"
            )
            return

        queues.setdefault(chat_id, []).append(path)
        n = len(queues[chat_id])
        await message.reply_text(
            f"✅ Video {n} received.\n"
            f"Send the next video, or use /done to join {n} video(s)."
        )


async def done(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id

    async with get_lock(chat_id):
        q = queues.pop(chat_id, [])

        if len(q) < 2:
            for p in q:
                shutil.rmtree(p.parent, ignore_errors=True)
            await update.message.reply_text(
                "⚠️ Send at least 2 videos before /done."
            )
            return

        status_msg = await update.message.reply_text(
            f"⚙️ Joining {len(q)} videos...\nPlease wait."
        )

        output_dir = Path(tempfile.mkdtemp(prefix="tgclip_out_"))
        output = output_dir / "final_clip.mp4"

        try:
            await asyncio.to_thread(run_ffmpeg_concat, q, output)

            with output.open("rb") as f:
                await update.message.reply_video(
                    video=f,
                    caption=f"✅ Done — {len(q)} videos joined.",
                    supports_streaming=True,
                )

            await status_msg.edit_text("✅ Processing complete.")
        except subprocess.CalledProcessError:
            log.exception("FFmpeg failed")
            await status_msg.edit_text(
                "❌ FFmpeg could not process one of the videos."
            )
        except Exception:
            log.exception("Unexpected processing error")
            await status_msg.edit_text(
                "❌ Something went wrong while creating the final video."
            )
        finally:
            for p in q:
                shutil.rmtree(p.parent, ignore_errors=True)
            shutil.rmtree(output_dir, ignore_errors=True)


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    log.exception("Unhandled Telegram error", exc_info=context.error)


def main():
    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("status", status))
    app.add_handler(CommandHandler("clear", clear))
    app.add_handler(CommandHandler("done", done))
    app.add_handler(
        MessageHandler(
            filters.VIDEO | filters.Document.VIDEO,
            receive_video,
        )
    )
    app.add_error_handler(error_handler)

    log.info("Bot is starting...")
    app.run_polling(
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=False,
    )


if __name__ == "__main__":
    main()
