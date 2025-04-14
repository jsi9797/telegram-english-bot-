import os
import openai
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters
from pydub import AudioSegment

openai.api_key = os.getenv("OPENAI_API_KEY")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")

user_profiles = {}
user_states = {}
user_histories = {}

survey_questions = [
    ("name", "📝 이름이 무엇인가요? (What is your name?)"),
    ("native", "🗣 모국어가 무엇인가요? (Your native language)?"),
    ("target", "📘 배우고 싶은 언어는 무엇인가요? (Which language would you like to learn?)"),
    ("age", "📅 나이대가 어떻게 되나요? (What is your age group?)"),
    ("gender", "👤 성별이 어떻게 되시나요? (남성/여성)"),
    ("level", "📊 현재 실력은 어느정도인가요? (예: 초급, 중급, 고급 또는 설명으로) (Your level: beginner/intermediate/advanced?)")
]

language_explanation = {
    "Korean": "설명은 한국어로 해주세요.",
    "Japanese": "説明は日本語でお願いします。",
    "Spanish": "Explica en español, por favor.",
    "Vietnamese": "Giải thích bằng tiếng Việt giúp tôi.",
    "Chinese": "请用中文解释。",
    "Indonesian": "Tolong jelaskan dalam Bahasa Indonesia."
}

def get_system_prompt(profile, history):
    explanation = language_explanation.get(profile.get("native", ""), "Explain in English.")
    name = profile.get("name", "학습자") + "님"
    history_summary = "\n".join(history[-3:])

    level = profile.get("level", "").lower()
    if "초" in level or "beginner" in level:
        native_ratio = 0.9
    elif "중" in level or "intermediate" in level:
        native_ratio = 0.5
    else:
        native_ratio = 0.2

    return f"""You are a GPT-based smart language tutor named CC4AI 튜터.
Your student's name is {name}.
They want to learn {profile.get("target", "English")} and their native language is {profile.get("native", "Korean")}.
Speak clearly, explain using their native language ({explanation}) at a {int(native_ratio*100)}% ratio.
Always begin by reacting to what they said. Then correct grammar and pronunciation if needed.
Give example sentences and encourage them to repeat aloud.
Then ask a related follow-up question or suggest a related expression.
Avoid repeating 'Do you want to learn more expressions?' often.
Keep track of conversation history and link lessons accordingly.
Recent conversation:
{history_summary}
"""

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_states[user_id] = 0
    user_profiles[user_id] = {}
    user_histories[user_id] = []
    await update.message.reply_text("👋 설문을 시작할게요! Please answer the following questions:")
    await ask_next_question(update, user_id)

async def ask_next_question(update, user_id):
    state = user_states[user_id]
    if state < len(survey_questions):
        key, question = survey_questions[state]
        await update.message.reply_text(question)
    else:
        await update.message.reply_text(f"✅ 설문이 완료되었습니다. 이제 수업을 시작할게요 {user_profiles[user_id]['name']}님!")
        del user_states[user_id]
        await tutor_response("수업을 시작하자", update, user_profiles[user_id])

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text.strip()

    if "설문조사" in text and "다시" in text:
        user_states[user_id] = 0
        user_profiles[user_id] = {}
        await update.message.reply_text("🔄 설문을 다시 시작할게요.")
        await ask_next_question(update, user_id)
        return

    if user_id in user_states:
        state = user_states[user_id]
        key, _ = survey_questions[state]
        user_profiles[user_id][key] = text
        user_states[user_id] += 1
        await ask_next_question(update, user_id)
    else:
        if user_id not in user_profiles:
            user_states[user_id] = 0
            user_profiles[user_id] = {}
            await update.message.reply_text("👋 설문부터 시작할게요!")
            await ask_next_question(update, user_id)
        else:
            await tutor_response(text, update, user_profiles[user_id])

async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in user_profiles:
        await update.message.reply_text("👋 설문 먼저 진행해주세요.")
        user_states[user_id] = 0
        user_profiles[user_id] = {}
        await ask_next_question(update, user_id)
        return

    file = await context.bot.get_file(update.message.voice.file_id)
    ogg_path = "voice.ogg"
    mp3_path = "voice.mp3"
    await file.download_to_drive(ogg_path)
    AudioSegment.from_ogg(ogg_path).export(mp3_path, format="mp3")

    with open(mp3_path, "rb") as f:
        transcript = openai.audio.transcriptions.create(model="whisper-1", file=f)

    await tutor_response(transcript.text, update, user_profiles[user_id])

async def tutor_response(user_input: str, update: Update, profile: dict):
    user_id = update.effective_user.id
    user_histories.setdefault(user_id, []).append(user_input)

    try:
        prompt = get_system_prompt(profile, user_histories[user_id])
        response = openai.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": prompt},
                {"role": "user", "content": user_input}
            ]
        )
        reply = response.choices[0].message.content
        user_histories[user_id].append(reply)
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
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_handler(MessageHandler(filters.VOICE, handle_voice))
    print("✅ CC4AI 튜터 작동 중")
    app.run_polling()
