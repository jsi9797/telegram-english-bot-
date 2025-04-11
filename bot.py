import os
import openai
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters
import requests
from pydub import AudioSegment

openai.api_key = os.getenv("OPENAI_API_KEY")

user_states = {}
user_profiles = {}
user_languages = {}
user_histories = {}  # 사용자별 대화 이력 저장용

survey_questions = [
    ("company", "✅ 회사명 (Your company name)?"),
    ("teacher", "✅ 강사 이름 (Your teacher's name)?"),
    ("native_language", "✅ 모국어가 무엇인가요? (Your native language?)"),
    ("target_language", "✅ 배우고 싶은 언어는 무엇인가요? (Which language would you like to learn?)"),
    ("age_group", "✅ 나이대가 어떻게 되나요? (What is your age group?)"),
    ("level", "✅ 현재 실력은 어느정도인가요? (예: 초급, 중급, 고급 또는 설명으로)\n(What's your level? e.g. beginner, intermediate, advanced or describe it)")
]

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
You are a professional but friendly language tutor.
Hold short daily conversation lessons in the student's target language.
After each student message:
- Correct grammar, expressions, and pronunciation if needed
- Explain errors in simple terms (in their native language)
- Encourage and expand the conversation naturally
- Ask a follow-up question based on the topic
{explanation}
Always stay warm, supportive, and engaging.
"""

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_states[user_id] = {"step": 0, "answers": {}}
    user_histories[user_id] = []
    await update.message.reply_text("👋 설문을 시작합니다!\nLet's start the survey!")
    await update.message.reply_text(survey_questions[0][1])

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text.strip()

    if user_id not in user_states and user_id not in user_profiles:
        await update.message.reply_text("/start 명령어로 설문을 먼저 시작해주세요. Please type /start to begin.")
        return

    if user_id in user_states:
        await handle_survey_step(user_id, text, update)
    else:
        await tutor_response(text, update, user_languages.get(user_id, "English"))

async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

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

    if user_id in user_states:
        await handle_survey_step(user_id, user_text, update)
    elif user_id in user_profiles:
        await tutor_response(user_text, update, user_languages.get(user_id, "English"))
    else:
        await update.message.reply_text("/start로 설문을 먼저 완료해주세요. Please complete the survey with /start first.")

async def handle_survey_step(user_id, text, update):
    state = user_states[user_id]
    step = state["step"]
    state["answers"][survey_questions[step][0]] = text
    state["step"] += 1

    if state["step"] < len(survey_questions):
        await update.message.reply_text(survey_questions[state["step"]][1])
    else:
        user_profiles[user_id] = state["answers"]
        user_languages[user_id] = user_profiles[user_id].get("native_language", "English")
        user_histories[user_id] = []
        del user_states[user_id]
        await update.message.reply_text("✅ 설문 완료! 수업을 시작할게요.\nSurvey complete! Let's begin the lesson.")
        await tutor_response("수업 시작", update, user_languages[user_id])

async def tutor_response(user_input: str, update: Update, language: str):
    user_id = update.effective_user.id
    history = user_histories.get(user_id, [])

    # 대화 이력 최대 5개까지 유지
    history.append({"role": "user", "content": user_input})
    if len(history) > 5:
        history = history[-5:]

    messages = [{"role": "system", "content": get_system_prompt(language)}] + history

    try:
        response = openai.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=messages
        )
        reply = response.choices[0].message.content
        history.append({"role": "assistant", "content": reply})
        user_histories[user_id] = history

        await update.message.reply_text(reply)

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

    print("✅ CC4AI Tutor with Contextual Dialogue is running")
    app.run_polling()
