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

BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]

LOCAL_API = os.environ.get(
    "TELEGRAM_LOCAL_API",
    "http://127.0.0.1:8081"
)

ALLOWED_USER_ID = os.environ.get("ALLOWED_USER_ID")

if ALLOWED_USER_ID:
    ALLOWED_USER_ID = int(ALLOWED_USER_ID)


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)

logger = logging.getLogger("TG-Video-Clipper")


queues = {}
locks = {}


def get_lock(chat_id):

    if chat_id not in locks:
        locks[chat_id] = asyncio.Lock()

    return locks[chat_id]


def is_allowed(update):

    if not ALLOWED_USER_ID:
        return True

    if not update.effective_user:
        return False

    return update.effective_user.id == ALLOWED_USER_ID


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if not is_allowed(update):
        await update.message.reply_text(
            "❌ You are not authorized to use this bot."
        )
        return

    await update.message.reply_text(
        "🎬 Telegram Video Clipper\n\n"
        "✅ Large-file mode enabled\n\n"
        "Send or forward videos in the order you want.\n\n"
        "Example:\n"
        "Video 1\n"
        "Video 2\n"
        "/done\n\n"
        "Commands:\n"
        "/status - show queue\n"
        "/clear - clear queue\n"
        "/done - join videos"
    )


async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if not is_allowed(update):
        return

    chat_id = update.effective_chat.id

    videos = queues.get(chat_id, [])

    await update.message.reply_text(
        f"📦 Videos in queue: {len(videos)}"
    )


async def clear(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if not is_allowed(update):
        return

    chat_id = update.effective_chat.id

    videos = queues.pop(chat_id, [])

    for video in videos:

        try:
            shutil.rmtree(
                video.parent,
                ignore_errors=True
            )
        except Exception:
            pass

    await update.message.reply_text(
        "🗑️ Queue cleared."
    )


async def receive_video(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if not is_allowed(update):

        await update.message.reply_text(
            "❌ You are not authorized to use this bot."
        )

        return


    message = update.message

    chat_id = update.effective_chat.id

    telegram_file = None

    filename = "video.mp4"


    # Normal Telegram video
    if message.video:

        telegram_file = await message.video.get_file()

        filename = (
            message.video.file_name
            or "video.mp4"
        )


    # Video sent as document
    elif message.document:

        mime = (
            message.document.mime_type
            or ""
        )

        if not mime.startswith("video/"):
            return

        telegram_file = (
            await message.document.get_file()
        )

        filename = (
            message.document.file_name
            or "video.mp4"
        )

    else:

        return


    async with get_lock(chat_id):

        work_dir = Path(
            tempfile.mkdtemp(
                prefix="tgclip_"
            )
        )


        filename = Path(
            filename
        ).name


        valid_extensions = (
            ".mp4",
            ".mkv",
            ".mov",
            ".avi",
            ".webm",
            ".m4v",
        )


        if not filename.lower().endswith(
            valid_extensions
        ):

            filename += ".mp4"


        video_path = (
            work_dir / filename
        )


        try:

            await update.message.reply_text(
                "⬇️ Downloading video...\n"
                "Large files may take some time."
            )


            await telegram_file.download_to_drive(
                custom_path=str(video_path)
            )


        except Exception as error:

            logger.exception(
                "Download failed"
            )

            shutil.rmtree(
                work_dir,
                ignore_errors=True
            )

            await update.message.reply_text(
                "❌ Video download failed.\n\n"
                f"Error: {error}"
            )

            return


        queues.setdefault(
            chat_id,
            []
        ).append(video_path)


        number = len(
            queues[chat_id]
        )


        await update.message.reply_text(
            f"✅ Video {number} received.\n\n"
            f"📦 Queue: {number} video(s)\n\n"
            "Send another video or use /done."
        )


def normalize_video(
    source,
    destination
):

    command = [

        "ffmpeg",

        "-y",

        "-hide_banner",

        "-loglevel",
        "error",

        "-i",
        str(source),

        "-map",
        "0:v:0",

        "-map",
        "0:a:0?",

        "-vf",
        "scale=trunc(iw/2)*2:trunc(ih/2)*2,"
        "format=yuv420p",

        "-r",
        "30",

        "-c:v",
        "libx264",

        "-preset",
        "veryfast",

        "-crf",
        "23",

        "-c:a",
        "aac",

        "-b:a",
        "128k",

        "-ar",
        "48000",

        "-movflags",
        "+faststart",

        str(destination),
    ]


    subprocess.run(
        command,
        check=True
    )


def join_videos(
    videos,
    output
):

    normalized_dir = (
        output.parent /
        "normalized"
    )

    normalized_dir.mkdir(
        parents=True,
        exist_ok=True
    )


    normalized = []


    for index, video in enumerate(videos):

        destination = (
            normalized_dir /
            f"part_{index:04d}.mp4"
        )

        logger.info(
            "Normalizing %s",
            video
        )

        normalize_video(
            video,
            destination
        )

        normalized.append(
            destination
        )


    concat_file = (
        normalized_dir /
        "concat.txt"
    )


    with concat_file.open(
        "w",
        encoding="utf-8"
    ) as file:

        for video in normalized:

            path = (
                video
                .resolve()
                .as_posix()
            )

            path = path.replace(
                "'",
                "'\\''"
            )

            file.write(
                f"file '{path}'\n"
            )


    command = [

        "ffmpeg",

        "-y",

        "-hide_banner",

        "-loglevel",
        "error",

        "-f",
        "concat",

        "-safe",
        "0",

        "-i",
        str(concat_file),

        "-c",
        "copy",

        "-movflags",
        "+faststart",

        str(output),
    ]


    logger.info(
        "Joining videos..."
    )


    subprocess.run(
        command,
        check=True
    )


async def done(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if not is_allowed(update):
        return


    chat_id = update.effective_chat.id


    async with get_lock(chat_id):

        videos = queues.pop(
            chat_id,
            []
        )


        if len(videos) < 2:

            for video in videos:

                shutil.rmtree(
                    video.parent,
                    ignore_errors=True
                )


            await update.message.reply_text(
                "⚠️ At least 2 videos are required."
            )

            return


        output_dir = Path(
            tempfile.mkdtemp(
                prefix="tgclip_output_"
            )
        )


        output = (
            output_dir /
            "final_clip.mp4"
        )


        status = await update.message.reply_text(
            f"⚙️ Processing {len(videos)} videos...\n\n"
            "Large videos can take a while."
        )


        try:

            await asyncio.to_thread(
                join_videos,
                videos,
                output
            )


            await status.edit_text(
                "📤 Uploading final video..."
            )


            with output.open(
                "rb"
            ) as file:

                await update.message.reply_video(
                    video=file,
                    caption=(
                        "✅ Final video ready!\n\n"
                        f"Joined videos: {len(videos)}"
                    ),
                    supports_streaming=True
                )


            await status.edit_text(
                "✅ Processing complete."
            )


        except subprocess.CalledProcessError:

            logger.exception(
                "FFmpeg failed"
            )

            await status.edit_text(
                "❌ FFmpeg failed while processing the videos."
            )


        except Exception as error:

            logger.exception(
                "Unexpected error"
            )

            await status.edit_text(
                "❌ Processing failed.\n\n"
                f"{error}"
            )


        finally:

            for video in videos:

                shutil.rmtree(
                    video.parent,
                    ignore_errors=True
                )


            shutil.rmtree(
                output_dir,
                ignore_errors=True
            )


async def error_handler(
    update,
    context
):

    logger.error(
        "Telegram error: %s",
        context.error
    )


def main():

    logger.info(
        "Starting Telegram Video Clipper..."
    )

    logger.info(
        "Local API: %s",
        LOCAL_API
    )


    application = (
        Application.builder()

        .token(
            BOT_TOKEN
        )

        .base_url(
            f"{LOCAL_API}/bot"
        )

        .base_file_url(
            f"{LOCAL_API}/file/bot"
        )

        .build()
    )


    application.add_handler(
        CommandHandler(
            "start",
            start
        )
    )


    application.add_handler(
        CommandHandler(
            "status",
            status
        )
    )


    application.add_handler(
        CommandHandler(
            "clear",
            clear
        )
    )


    application.add_handler(
        CommandHandler(
            "done",
            done
        )
    )


    application.add_handler(
        MessageHandler(
            filters.VIDEO
            |
            filters.Document.VIDEO,
            receive_video
        )
    )


    application.add_error_handler(
        error_handler
    )


    logger.info(
        "Bot is online."
    )


    application.run_polling(
        allowed_updates=Update.ALL_TYPES
    )


if __name__ == "__main__":

    main()
