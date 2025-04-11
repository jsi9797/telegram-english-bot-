import os
import openai
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters
from pydub import AudioSegment

openai.api_key = os.getenv("OPENAI_API_KEY")

# /start 명령어 처리
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("안녕하세요! 🎙 텍스트 또는 음성을 보내면 영어 문장을 교정해드릴게요!")

# 텍스트 메시지 처리
async def correct_english(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_input = update.message.text
    prompt = f"Correct this English sentence and explain briefly:\n\n\"{user_input}\""

    try:
        # GPT 호출
        response = openai.ChatCompletion.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": "You are a helpful English teacher."},
                {"role": "user", "content": prompt}
            ]
        )
        reply = response["choices"][0]["message"]["content"]
        await update.message.reply_text(reply)

        # 음성 응답 생성 (TTS)
        tts_response = openai.Audio.speech.create(
            model="tts-1",
            voice="nova",
            input=reply
        )
        tts_path = "response.mp3"
        with open(tts_path, "wb") as f:
            f.write(tts_response.content)

        # 텔레그램에 음성 파일 전송
        with open(tts_path, "rb") as voice_file:
            await update.message.reply_voice(voice=voice_file)

    except Exception as e:
        await update.message.reply_text(f"❌ 오류 발생: {str(e)}")

# 음성 메시지 처리
async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    file = await context.bot.get_file(update.message.voice.file_id)
    ogg_path = "user_voice.ogg"
    mp3_path = "user_voice.mp3"

    # 다운로드 및 변환
    await file.download_to_drive(ogg_path)
    AudioSegment.from_ogg(ogg_path).export(mp3_path, format="mp3")

    try:
        # Whisper로 음성 → 텍스트 변환
        with open(mp3_path, "rb") as f:
            transcript = openai.Audio.transcribe(model="whisper-1", file=f)

        user_text = transcript["text"]
        await update.message.reply_text(f"🗣 인식된 문장: {user_text}")

        # 텍스트 처리 로직 재사용
        update.message.text = user_text
        await correct_english(update, context)

    except Exception as e:
        await update.message.reply_text(f"❌ 음성 인식 오류: {str(e)}")

# 봇 실행
if __name__ == '__main__':
    TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, correct_english))
    app.add_handler(MessageHandler(filters.VOICE, handle_voice))

    print("🤖 Bot is running with GPT + TTS + Whisper")
    app.run_polling()
