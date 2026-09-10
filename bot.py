import os
import subprocess
from pyrogram import Client, filters
from pyrogram.types import Message

# Yahan par names aapke GitHub secrets (1000828221.jpg) ke hisaab se update kar diye hain
API_ID = os.environ.get("TELEGRAM_API_ID")
API_HASH = os.environ.get("TELEGRAM_API_HASH")
BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")

if not all([API_ID, API_HASH, BOT_TOKEN]):
    raise ValueError("Missing Credentials. Please check GitHub Secrets.")

app = Client("video_clipper_bot", api_id=int(API_ID), api_hash=API_HASH, bot_token=BOT_TOKEN)

# ... (baaki ka poora code bilkul same rahega jo pehle diya tha) ...
app = Client("video_clipper_bot", api_id=int(API_ID), api_hash=API_HASH, bot_token=BOT_TOKEN)

# User state track karne ke liye (kaunse user ne kitne videos bheje hain)
user_videos = {}

@app.on_message(filters.command("start"))
async def start(client, message: Message):
    await message.reply_text(
        "Hello! Main ek Video Clipper Bot hoon.\n"
        "Mujhe 2 video clips forward ya send karein, aur main unhe FFmpeg se merge karke aapko de dunga."
    )

@app.on_message(filters.video)
async def handle_video(client, message: Message):
    user_id = message.from_user.id

    if user_id not in user_videos:
        user_videos[user_id] = []

    # Video message ko list me save karein
    user_videos[user_id].append(message)

    if len(user_videos[user_id]) == 1:
        await message.reply_text("✅ Pehla video mil gaya! Ab doosra video send ya forward karein.")
    
    elif len(user_videos[user_id]) == 2:
        status_msg = await message.reply_text("⏳ Dono videos mil gaye. Processing shuru ho rahi hai...")

        vid1_path, vid2_path, output_path = None, None, None

        try:
            # Videos download kar rahe hain
            await status_msg.edit_text("📥 Pehla video download ho raha hai...")
            vid1_path = await user_videos[user_id][0].download(file_name=f"downloads/{user_id}_1.mp4")

            await status_msg.edit_text("📥 Doosra video download ho raha hai...")
            vid2_path = await user_videos[user_id][1].download(file_name=f"downloads/{user_id}_2.mp4")

            output_path = f"downloads/{user_id}_merged.mp4"
            await status_msg.edit_text("⚙️ FFmpeg se videos merge ho rahe hain... Isme thoda time lag sakta hai.")

            # FFmpeg Command (Dono clips ko aapas me jodna)
            command = [
                "ffmpeg", "-y",
                "-i", vid1_path,
                "-i", vid2_path,
                "-filter_complex", "[0:v][0:a][1:v][1:a]concat=n=2:v=1:a=1[outv][outa]",
                "-map", "[outv]",
                "-map", "[outa]",
                output_path
            ]

            process = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

            if process.returncode != 0:
                print(process.stderr.decode())
                await status_msg.edit_text("❌ Merging fail ho gayi. (Check karein ki dono videos me Audio aur Video streams mojud hon).")
            else:
                await status_msg.edit_text("📤 Merge complete! Video upload ho raha hai...")
                
                # Direct reply use kar rahe hain, isme alag se ID dene ki zaroorat nahi hai
                await message.reply_video(
                    video=output_path, 
                    caption="🎬 Ye raha aapka merged video!"
                )
                await status_msg.delete()

        except Exception as e:
            await status_msg.edit_text(f"⚠️ Ek error aagaya: {e}")

        finally:
            # Kaam hone ke baad temporary list aur files delete karna taaki storage clear rahe
            user_videos[user_id] = []
            for f in [vid1_path, vid2_path, output_path]:
                if f and os.path.exists(f):
                    os.remove(f)

if __name__ == "__main__":
    if not os.path.exists("downloads"):
        os.makedirs("downloads")
    print("Bot is running...")
    app.run()
