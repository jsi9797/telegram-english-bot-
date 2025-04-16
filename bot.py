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
user_sentences = {}
user_sentence_index = {}

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
    level = profile.get("level", "beginner").lower()
    return f'''
You are a GPT-based smart English tutor.
Speak slowly and clearly. The learner is {level} level.
Use {profile['native']} to explain, but give examples in {profile['target']}.
Teach step-by-step:
When a topic is given:
1. First, generate a list of 3-5 simple example sentences related to the topic in {profile['target']}.
2. For each sentence, present:
   - English sentence
   - Translation in {profile['native']}
   - Vocabulary explanation
   - Then say: "이 문장을 한번 따라 말해보고, 준비가 되면 녹음하여 전송해주세요!"
Wait for the learner to speak, then give pronunciation feedback.
After feedback, move to the next sentence. Repeat until done.
'''

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
        await update.message.reply_text("✅ 설문 완료! 이제 수업을 시작할게요.")
        del user_states[user_id]
        await update.message.reply_text("무슨 주제로 수업을 시작해볼까요?")

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text.strip()

    if user_id not in user_profiles or not user_profiles[user_id].get("level"):
        if user_id not in user_states:
            user_states[user_id] = 0
            user_profiles[user_id] = {}
            await update.message.reply_text("👋 설문을 시작합니다! Let's start the survey!")
        state = user_states[user_id]
        key, _ = survey_questions[state]
        user_profiles[user_id][key] = text
        user_states[user_id] += 1
        await ask_next_question(update, user_id)
        return

    user_topics[user_id] = text
    user_sentence_index[user_id] = 0
    await generate_sentences(update, user_id)

async def generate_sentences(update, user_id):
    profile = user_profiles[user_id]
    system_prompt = get_system_prompt(profile)

    response = openai.chat.completions.create(
        model="gpt-3.5-turbo",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"Please create 3 example sentences for the topic '{user_topics[user_id]}' with translations and explanations."}
        ]
    )

    content = response.choices[0].message.content
    user_sentences[user_id] = content.split("

")  # 나눠서 저장
    await present_sentence(update, user_id)

async def present_sentence(update, user_id):
    index = user_sentence_index[user_id]
    sentences = user_sentences.get(user_id, [])
    if index < len(sentences):
        msg = f"{sentences[index]}

🗣 이 문장을 한번 따라 말해보고, 준비가 되면 녹음하여 전송해주세요!"
        await update.message.reply_text(msg)
    else:
        await update.message.reply_text("👍 오늘의 문장을 모두 연습했어요! 수고하셨습니다.")

async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in user_profiles:
        await update.message.reply_text("처음 오셨군요! 설문부터 시작할게요 📝")
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

    await pronunciation_feedback(update, user_id, transcript.text)

async def pronunciation_feedback(update, user_id, text):
    profile = user_profiles[user_id]
    sentence = user_sentences[user_id][user_sentence_index[user_id]]
    messages = [
        {"role": "system", "content": "You are an English tutor specialized in pronunciation feedback."},
        {"role": "user", "content": f"The learner said: '{text}'. Please give detailed pronunciation feedback based on the target sentence: {sentence}"}
    ]
    response = openai.chat.completions.create(
        model="gpt-3.5-turbo",
        messages=messages
    )
    feedback = response.choices[0].message.content
    await update.message.reply_text(f"📣 피드백: {feedback}")

    # 다음 문장 진행
    user_sentence_index[user_id] += 1
    await present_sentence(update, user_id)

if __name__ == "__main__":
    openai.api_key = os.getenv("OPENAI_API_KEY")
    app = ApplicationBuilder().token(os.getenv("TELEGRAM_TOKEN")).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_handler(MessageHandler(filters.VOICE, handle_voice))
    print("✅ CC4AI 튜터 작동 중")
    app.run_polling()
