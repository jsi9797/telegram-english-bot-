import os
import openai
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters
import requests
from pydub import AudioSegment

openai.api_key = os.getenv("OPENAI_API_KEY")

# 사용자별 언어 설정 저장용 딕셔너리
user_languages = {}

# 기본 시스템 프롬프트 (튜터 스타일)
def get_system_prompt(language):
    explanation = {
        "Korean": "설명은 한국어로 해주세요.",
        "Japanese": "説明は日本語でお願いします。",
        "Spanish": "Explica en español, por favor.",
        "Vietnamese": "Giải thích bằng tiếng Việt giúp tôi.",
        "Chinese": "请用中文解释。",
        "Indonesian": "Tolong jelaskan dalam Bahasa Indonesia."
    }.get(language, "Explain in English.")

    return f"""
You are a friendly and professional language tutor.
When the student says things like 'Let's start' or 'Teach me',
you start a mini-lesson with useful daily expressions and short dialogue practice.
Today's topic is talking about the weather.
Teach 2-3 useful expressions, give examples, and ask the student to try responding.
Correct them kindly and provide both encouragement and a voice reply.
{explanation}
Always keep your tone kind, simple, and supportive.
"""

# 언어 선택 프롬프트
language_prompt = """
🌍 Before we begin, which language would you like explanations in?

🇰🇷 Korean
🇯🇵 Japanese
🇨🇳 Chinese
🇪🇸 Spanish
🇻🇳 Vietnamese
🇮🇩 Indonesian
🇺🇸 English (default)

Please type one of the above to continue!
"""

# /start 명령
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in user_languages:
        await update.message.reply_text(language_prompt)
    else:
        await update.message.reply_text("🎙 수업을 시작할게요! 텍스트나 음성을 입력해주세요.")

# 텍스트 메시지 처리
async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_input = update.message.text.strip().lower()

    # 언어 설정 처리
    if user_id not in user_languages:
        if user_input in ["korean", "한국어"]:
            user_languages[user_id] = "Korean"
        elif user_input in ["japanese", "日本語"]:
            user_languages[user_id] = "Japanese"
        elif user_input in ["spanish", "español"]:
            user_languages[user_id] = "Spanish"
        elif user_input in ["vietnamese", "tiếng việt"]:
            user_languages[user_id] = "Vietnamese"
        elif user_input in ["chinese", "中文", "mandarin"]:
            user_languages[user_id] = "Chinese"
        elif user_input in ["indonesian", "bahasa"]:
            user_languages[user_id] = "Indonesian"
        elif user_input in ["english"]:
            user_languages[user_id] = "English"
        else:
            await update.message.reply_text("❗ 언어를 인식하지 못했어요. 다시 입력해주세요. 예: Korean")
            return
        await update.message.reply_text("✅ 언어 설정 완료! 이제 수업을 시작합니다.")
        return

    await tutor_response(user_input, update, user_languages[user_id])

# 음성 메시지 처리
async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in user_languages:
        await update.message.reply_text(language_prompt)
        return

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
    await tutor_response(user_text, update, user_languages[user_id])

# GPT 튜터 응답 처리
async def tutor_response(user_input: str, update: Update, language: str):
    try:
        response = openai.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": get_system_prompt(language)},
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

    print("✅ CC4AI Tutor with Full Language Support is running")
    app.run_polling()

    app.run_polling()
