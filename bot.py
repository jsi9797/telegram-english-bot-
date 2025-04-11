import os
import openai
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters
import requests
from pydub import AudioSegment

openai.api_key = os.getenv("OPENAI_API_KEY")

# ✅ 시스템 프롬프트 (튜터 스타일)
TUTOR_SYSTEM_PROMPT = """
You are a friendly and professional English tutor.
When the student says things like 'Let's start' or 'Teach me',
you start a mini-lesson with useful daily expressions and short dialogue practice.
Today's topic is talking about the weather.
Teach 2-3 useful expressions, give examples, and ask the student to try responding.
Correct them kindly and provide both encouragement and a voice reply.
Always keep your tone kind, simple, and supportive.
"""

# /start 명령
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🎙 음성 또는 텍스트를 입력하면 영어 수업을 시작해드릴게요!")

# 텍스트 메시지 처리
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_input = update.message.text
    await tutor_response(user_input, update)

# 음성 메시지 처리
async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    file = await context.bot.get_file(update.message.voice.file_id)
    ogg_path = "voice.ogg"
    mp3_path = "voice.mp3"
    await file.download_to_drive(ogg_path)
    AudioSegment.from_ogg(ogg_path).export(mp3_path, format="mp3")

    with open(mp3_path, "rb") as f:
        transcript = openai.audio.transcriptions.create(
            model="whisper-1",
            file=f
        )

    user_text = transcript.text
    await tutor_response(user_text, update)

# GPT 튜터 응답 처리
async def tutor_response(user_input: str, update: Update):
    try:
        response = openai.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": TUTOR_SYSTEM_PROMPT},
                {"role": "user", "content": user_input}
            ]
        )
        reply = response.choices[0].message.content
        await update.message.reply_text(reply)

        # 음성 생성
        speech = openai.audio.speech.create(
            model="tts-1",
            voice="nova",
            input=reply
        )
        tts_path = "response.mp3"
        with open(tts_path, "wb") as f:
            f.write(speech.content)

        await update.message.reply_voice(voice=open(tts_path, "rb"))

    except Exception as e:
        await update.message.reply_text(f"❌ 오류 발생: {str(e)}")

if __name__ == "__main__":
    app = ApplicationBuilder().token(os.getenv("TELEGRAM_TOKEN")).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_handler(MessageHandler(filters.VOICE, handle_voice))

    print("✅ CC4AI Tutor is running")
    app.run_polling()
