import os
from openai import OpenAI
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters
from pydub import AudioSegment

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# /start 명령어 처리
def get_env_token():
    return os.getenv("TELEGRAM_TOKEN")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("안녕하세요! 🎙 음성 또는 텍스트를 입력하면 교정해드릴게요!")

# 영어 문장 교정 및 음성 응답 생성
async def correct_english(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        user_input = update.message.text
        await update.message.reply_text("🛠 교정 함수 진입 확인")

        prompt = f"Correct this English sentence and explain briefly:\n\n\"{user_input}\""

        response = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": "You are a helpful English teacher."},
                {"role": "user", "content": prompt},
            ]
        )

        reply = response.choices[0].message.content
        await update.message.reply_text(reply)

        # TTS 생성
        tts_response = client.audio.speech.create(
            model="tts-1",
            voice="nova",
            input=reply
        )

        with open("response.mp3", "wb") as f:
            f.write(tts_response.content)

        await update.message.reply_voice(voice=open("response.mp3", "rb"))

    except Exception as e:
        await update.message.reply_text(f"❌ 오류 발생: {str(e)}")

# 음성 메시지 처리
async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        file = await context.bot.get_file(update.message.voice.file_id)
        ogg_path = "voice.ogg"
        mp3_path = "voice.mp3"
        await file.download_to_drive(ogg_path)
        AudioSegment.from_ogg(ogg_path).export(mp3_path, format="mp3")

        with open(mp3_path, "rb") as f:
            transcript = client.audio.transcriptions.create(
                model="whisper-1",
                file=f
            )

        user_text = transcript.text
        await update.message.reply_text(f"🗣 인식된 문장: {user_text}")

        # GPT 교정으로 넘기기
        update.message.text = user_text
        await correct_english(update, context)

    except Exception as e:
        await update.message.reply_text(f"❌ 음성 처리 오류: {str(e)}")

if __name__ == '__main__':
    app = ApplicationBuilder().token(get_env_token()).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, correct_english))
    app.add_handler(MessageHandler(filters.VOICE, handle_voice))

    print("🤖 Bot is running with GPT + Voice")
    app.run_polling()
