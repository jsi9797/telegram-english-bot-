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

def get_system_prompt(profile):
    explanation = language_explanation.get(profile['native'], "Explain in English.")
    return f"""You are a GPT-based smart tutor. Speak slowly and clearly. Use examples in {profile['target']} and explain in {profile['native']}.
First, provide 5 to 10 vocabulary words with translations. Ask the learner to repeat them.
After that, move to 3 to 5 example sentences and ask the learner to repeat each.
Only after repeating each sentence, proceed to the next one. 
Give kind feedback and guide pronunciation if in 'pronunciation' mode.
{explanation}
"""

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_profiles[user_id] = {}
    user_states[user_id] = 0
    await update.message.reply_text("👋 설문을 시작합니다! Let's start the survey!")
    await ask_next_question(update, user_id)

async def ask_next_question(update, user_id):
    state = user_states[user_id]
    if state < len(survey_questions):
        key, question = survey_questions[state]
        await update.message.reply_text(question)
    else:
        await update.message.reply_text("✅ 설문 완료! 이제 수업을 시작할게요.")
        del user_states[user_id]
        await update.message.reply_text("무슨 주제로 수업을 시작할까요?")

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text.strip()

    if user_id not in user_profiles or 'level' not in user_profiles[user_id]:
        if user_id not in user_states:
            user_profiles[user_id] = {}
            user_states[user_id] = 0
        state = user_states[user_id]
        key, _ = survey_questions[state]
        user_profiles[user_id][key] = text
        user_states[user_id] += 1
        await ask_next_question(update, user_id)
        return

    if user_id not in user_topics or not user_topics[user_id]:
        user_topics[user_id] = text
        await update.message.reply_text(f"좋아요. '{text}' 주제로 수업을 시작할게요.")
        await tutor_response(f"Start vocabulary lesson about {text}", update, user_profiles[user_id])
        return

    await tutor_response(text, update, user_profiles[user_id])

async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in user_profiles:
        await update.message.reply_text("먼저 설문을 완료해주세요.")
        return

    file = await context.bot.get_file(update.message.voice.file_id)
    ogg_path = "voice.ogg"
    mp3_path = "voice.mp3"
    await file.download_to_drive(ogg_path)
    AudioSegment.from_ogg(ogg_path).export(mp3_path, format="mp3")
    with open(mp3_path, "rb") as f:
        transcript = openai.audio.transcriptions.create(model="whisper-1", file=f)

    await tutor_response(transcript.text, update, user_profiles[user_id], mode="pronunciation")

async def tutor_response(user_input: str, update: Update, profile: dict, mode: str = None):
    user_id = update.effective_user.id
    if user_id not in user_histories:
        user_histories[user_id] = []
    if user_id not in user_topics:
        user_topics[user_id] = user_input

    system_prompt = get_system_prompt(profile)
    messages = [{"role": "system", "content": system_prompt}]

    if mode == "pronunciation":
        messages.append({
            "role": "user",
            "content": f"The learner said: '{user_input}'. Please analyze pronunciation and provide feedback word by word."
        })
    else:
        messages.append({
            "role": "user",
            "content": user_input
        })

    messages += user_histories[user_id][-10:]

    response = openai.chat.completions.create(model="gpt-3.5-turbo", messages=messages)
    reply = response.choices[0].message.content
    user_histories[user_id].append({"role": "user", "content": user_input})
    user_histories[user_id].append({"role": "assistant", "content": reply})
    await update.message.reply_text(reply)

    speech = openai.audio.speech.create(model="tts-1", voice="nova", input=reply)
    tts_path = "response.mp3"
    with open(tts_path, "wb") as f:
        f.write(speech.content)
    await update.message.reply_voice(voice=open(tts_path, "rb"))

if __name__ == "__main__":
    openai.api_key = os.getenv("OPENAI_API_KEY")
    app = ApplicationBuilder().token(os.getenv("TELEGRAM_TOKEN")).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_handler(MessageHandler(filters.VOICE, handle_voice))
    print("✅ Tutor bot is running")
    app.run_polling()
