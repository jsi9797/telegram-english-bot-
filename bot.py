import os
import openai
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters
import requests
from pydub import AudioSegment

user_profiles = {}
user_states = {}
user_histories = {}
user_topics = {}

survey_questions = [
    ("native", "🗣 모국어가 무엇인가요? (Your native language)?"),
    ("target", "📘 배우고 싶은 언어는 무엇인가요? (Which language would you like to learn?)"),
    ("age", "📅 나이대가 어떻게 되나요? (What is your age group?)"),
    ("gender", "👤 성별이 어떻게 되시나요? (남성/여성)"),
    ("level", "📊 현재 실력은 어느정도인가요? (Your level: beginner/intermediate?)")
]

language_explanation = {
    "Korean": "설명은 한국어로 해주세요.",
    "Japanese": "説明は日本語でお願いします。",
    "Spanish": "Explica en español, por favor.",
    "Vietnamese": "Giải thích bằng tiếng Việt giúp tôi.",
    "Chinese": "请用中文解释。",
    "Indonesian": "Tolong jelaskan dalam Bahasa Indonesia."
}

def get_system_prompt(profile):  # 💡 Modified to reflect level-based instruction language handling
    explanation = language_explanation.get(profile['native'], "Explain in English.")
    level = profile.get("level", "beginner").lower()

    if "중급" in level or "intermediate" in level:
        return f"""
You are a GPT-based smart English tutor.
Speak slowly and clearly. The learner is intermediate level.
The native language is {profile['native']}, and the target language is {profile['target']}.
Use {profile['native']} only for grammar explanations or corrections.
Conduct the class strictly in {profile['target']}, unless explanation is needed.
Start with a topic the learner gives, ask for more context, and then practice realistic English dialogues.
Correct errors in grammar and pronunciation and give feedback naturally.
Encourage short conversations or role-play.
After every interaction, guide the learner to the next example sentence or context without ending the session abruptly.
"""
You are a GPT-based smart English tutor.
Speak slowly and clearly. The learner is intermediate level.
The native language is {profile['native']}, and the target language is {profile['target']}.
Use {profile['native']} only for grammar explanations or corrections.
Start with a topic the learner gives, ask for more context, and then practice realistic English dialogues.
Correct errors in grammar and pronunciation and give feedback naturally.
Encourage short conversations or role-play.
"""
    else:
        return f"""
You are a GPT-based smart English tutor.
Speak very slowly and clearly. The learner is beginner level.
Use {profile['native']} for 80% of the explanation, and use {profile['target']} only in short, easy sentences.
Conduct the class in {profile['target']} with support in {profile['native']}.
When a topic is given (e.g., travel, computer), break it into subtopics.
Give 2-3 short example sentences and basic vocabulary with explanation.
Ask the learner to repeat and give pronunciation feedback.
Then immediately guide them to the next phrase or practice sentence.
Never stop with "you did great" only — always follow up with next content.
Make it interactive and guide them step-by-step.
"""

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_states[user_id] = 0
    user_profiles[user_id] = {}
    await update.message.reply_text("👋 설문을 시작합니다! Let's start the survey!")
    await ask_next_question(update, user_id)

async def ask_next_question(update, user_id):
    state = user_states[user_id]
    if state < len(survey_questions):
        key, question = survey_questions[state]
        await update.message.reply_text(question)
    else:
        await update.message.reply_text("✅ 설문 완료! 이제 수업을 시작할게요 형님.")
        del user_states[user_id]
        await update.message.reply_text("무슨 주제로 수업을 시작해볼까요?")

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text.strip()

    if user_id in user_states:
        state = user_states[user_id]
        key, _ = survey_questions[state]
        user_profiles[user_id][key] = text
        user_states[user_id] += 1
        await ask_next_question(update, user_id)
    else:
        profile = user_profiles.get(user_id)
        if profile:
            await tutor_response(text, update, profile)
        else:
            await update.message.reply_text("처음 오셨군요! 설문부터 진행할게요 형님 📝")
            user_states[user_id] = 0
            user_profiles[user_id] = {}
            await ask_next_question(update, user_id)

async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in user_profiles:
        await update.message.reply_text("처음 오셨군요! 설문부터 진행할게요 형님 📝")
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
    try:
        user_id = update.effective_user.id
        system_prompt = get_system_prompt(profile)

        if user_id not in user_histories:
            user_histories[user_id] = []

        if user_id not in user_topics:
            user_topics[user_id] = None

        # 주제를 처음 정했을 경우 저장
        if user_topics[user_id] is None and any(keyword in user_input.lower() for keyword in ['여행', '컴퓨터', '비즈니스', '코딩', '영어 수업', 'travel', 'computer', 'business', 'coding', 'english lesson']):
            user_topics[user_id] = user_input

        user_histories[user_id].append({"role": "user", "content": user_input})
        history = user_histories[user_id][-10:]
        messages = [{"role": "system", "content": system_prompt}] + history

        response = openai.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=messages
        )

        reply = response.choices[0].message.content
        user_histories[user_id].append({"role": "assistant", "content": reply})

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
    openai.api_key = os.getenv("OPENAI_API_KEY")
    app = ApplicationBuilder().token(os.getenv("TELEGRAM_TOKEN")).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_handler(MessageHandler(filters.VOICE, handle_voice))
    print("✅ CC4AI 튜터 작동 중")
    app.run_polling()
