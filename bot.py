import os
import openai
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters
import requests
from pydub import AudioSegment

openai.api_key = os.getenv("OPENAI_API_KEY")

# /start 명령 처리
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("안녕하세요! 음성 또는 텍스트를 입력하면 교정해드릴게요!")

# 텍스트 메시지 처리
async def correct_english(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_input = update.message.text
    prompt = f"Correct this English sentence and explain briefly:\n\n\"{user_input}\""

    try:
        response = openai.ChatCompletion.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": "You are a helpful English teacher."},
                {"role": "user", "content": prompt}
            ]
        )
        reply = response["choices"][0]["message"]["content"]
        await update.message.reply_text(reply)

        # 음성 응답 생성
        tts_response = openai.audio.speech.create(
            model="tts-1",
            voice="nova",
            input=reply
        )

        tts_path = "response.mp3"
        with open(tts_path, "wb") as f:
            f.write(tts_response.content)

        await update.message.reply_voice(voice=open(tts_path, "rb"))

    except Exception as e:
        await update.message.reply_text(f"❌ 오류 발생: {str(e)}")

# 음성 메시지 처리
async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    file = await context.bot.get_file(update.message.voice.file_id)
    ogg_path = "voice.ogg"
    mp3_path = "voice.mp3"
    await file.download_to_drive(ogg_path)
    AudioSegment.from_ogg(ogg_path).export(mp3_path, format="mp3")

    with open(mp3_path, "rb") as f:
        transcript = openai.Audio.transcribe(model="whisper-1", file=f)

    user_text = transcript["text"]
    await update.message.reply_text(f"🗣 인식된 문장: {user_text}")

    # 텍스트 교정 재사용
    update.message.text = user_text
    await correct_english(update, context)

if __name__ == '__main__':
    app = ApplicationBuilder().token(os.getenv("TELEGRAM_TOKEN")).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, correct_english))
    app.add_handler(MessageHandler(filters.VOICE, handle_voice))

    print("Bot is running with GPT + Voice")  # ← 이모지 제거 완료
    app.run_polling()
