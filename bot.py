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
    level = profile.get("level", "beginner").lower()
    return f"""
You are a GPT-based smart English tutor.
Speak slowly and clearly. The learner is {level} level.
Use {profile['native']} to explain, but give examples in {profile['target']}.
Teach step-by-step: 
1. First, introduce 5-10 vocabulary words with {profile['native']} meaning.
2. Prompt user to repeat each word aloud. Wait for their audio.
3. Give pronunciation feedback.
4. When pronunciation is complete, continue to 3-5 example sentences.
5. Present English sentence, then native translation, then ask learner to repeat aloud.
6. Give pronunciation and grammar feedback after each sentence.
Make learning interactive and natural.
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

    await tutor_response(text, update, user_profiles[user_id])

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

    if 'retry_count' not in user_profiles[user_id]:
        user_profiles[user_id]['retry_count'] = 0
    if 'last_phrase' not in user_profiles[user_id]:
        user_profiles[user_id]['last_phrase'] = transcript.text

    if user_profiles[user_id]['retry_count'] >= 2:
        user_profiles[user_id]['retry_count'] = 0
        user_profiles[user_id]['last_phrase'] = ''
        user_profiles[user_id]['vocab_phase'] = False
    else:
        user_profiles[user_id]['retry_count'] += 1

    await tutor_response(transcript.text, update, user_profiles[user_id], mode="pronunciation")

async def tutor_response(user_input: str, update: Update, profile: dict, mode: str = None):
    try:
        user_id = update.effective_user.id
        system_prompt = get_system_prompt(profile)

        if user_id not in user_histories:
            user_histories[user_id] = []
        if user_id not in user_topics:
            user_topics[user_id] = None
        if user_topics[user_id] is None:
            user_topics[user_id] = user_input

        user_histories[user_id].append({"role": "user", "content": user_input})

        if 'vocab_phase' not in user_profiles[user_id]:
            user_profiles[user_id]['vocab_phase'] = True

        messages = [{"role": "system", "content": system_prompt}]
        history = [msg for msg in user_histories[user_id][-10:] if msg.get("content")]
        messages += history

        if mode == "pronunciation":
            messages.append({
                "role": "user",
                "content": f"The learner said: '{user_input}'. Please carefully analyze the pronunciation word-by-word.\n"
                           "✅ Clear if the pronunciation is accurate.\n"
                           "⚠️ Needs improvement if the word was unclear, distorted, or incorrect.\n"
                           "Give honest and strict evaluation. If more than 2 words are not clear, ask the learner to try again."
            })
        elif user_profiles[user_id]['vocab_phase']:
            messages.append({
                "role": "user",
                "content": f"Please start an English lesson using the topic '{user_topics[user_id]}'. "
                           f"First, introduce 5 to 10 vocabulary words in {profile['target']} with translations in {profile['native']}. "
                           "After listing the vocabulary, say: '각 단어를 읽어보시고 준비가 되면 녹음하여 전송 해주세요.' "
                           "Do not continue to example sentences until the learner completes pronunciation."
            })
        else:
            messages.append({
                "role": "user",
                "content": f"Now continue the lesson by providing 3 to 5 example sentences related to the topic '{user_topics[user_id]}'. "
                           f"For each sentence: 1) Present the English version, 2) Translate it into {profile['native']}, "
                           "and 3) Ask the learner to repeat the sentence aloud. Wait for the learner’s response before presenting the next sentence."
            })

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
