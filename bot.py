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
Speak very slowly and clearly. The learner is beginner level.
Use {profile['native']} to explain most of the content and instructions, but provide all English examples and practice in {profile['target']}.
Deliver all practice content in {profile['target']} and provide supportive explanation in {profile['native']} when necessary to aid understanding.
When a topic is given (e.g., travel, computer), break it into subtopics.
For each example sentence:
- Provide the English sentence.
- Translate it into the learner's native language.
- Explain key vocabulary with meaning in the native language.
- Ask the learner to repeat the sentence aloud.
- After listening, give pronunciation and grammar feedback.
After the learner finishes 3-4 sentences, ask them a question that allows them to use the learned expressions in a short, creative response. Guide the learner to practice and build confidence.
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

    # 이미 설문이 완료된 경우 user_states 에 존재하지 않으면 바로 수업 시작
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

    # 설문 완료 후 일반 메시지 처리
    await tutor_response(text, update, user_profiles[user_id])
    return  # 중복 실행 방지

async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global user_profiles
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
    else:
        user_profiles[user_id]['retry_count'] += 1
        # 발음 완료 시 문장 학습으로 전환
    if user_profiles[user_id]['retry_count'] >= 2:
        user_profiles[user_id]['retry_count'] = 0
        user_profiles[user_id]['last_phrase'] = ''
        user_profiles[user_id]['vocab_phase'] = False

    await tutor_response(transcript.text, update, user_profiles[user_id], mode="pronunciation")

async def tutor_response(user_input: str, update: Update, profile: dict, mode: str = None):
    try:
        user_id = update.effective_user.id
        system_prompt = get_system_prompt(profile)
        if not system_prompt or not isinstance(system_prompt, str):
            system_prompt = "You are a helpful tutor. Please guide the learner step-by-step."

        if user_id not in user_histories:
            user_histories[user_id] = []

        if user_id not in user_topics:
            user_topics[user_id] = None

        # 주제를 처음 정했을 경우 저장
        if user_topics[user_id] is None:
            user_topics[user_id] = user_input

        user_histories[user_id].append({"role": "user", "content": user_input})

        # 단어와 문장이 섞이지 않도록 제어
        if 'vocab_phase' not in user_profiles[user_id]:
            user_profiles[user_id]['vocab_phase'] = True

        if user_profiles[user_id]['vocab_phase'] and mode != "pronunciation":
            messages.append({"role": "user", "content": f"Please start an English lesson using the topic '{user_topics[user_id]}'. First, introduce 5 to 10 vocabulary words in {profile['target']} with translations in {profile['native']}. After listing the vocabulary, say: '각 단어를 읽어보시고 준비가 되면 녹음하여 전송 해주세요.' Do not include additional instructions or explanations. Do not continue to example sentences until the learner finishes the pronunciation step."})
        elif not user_profiles[user_id]['vocab_phase'] and mode != "pronunciation":
            messages.append({"role": "user", "content": f"Now continue the lesson by providing 3 to 5 example sentences related to the topic '{user_topics[user_id]}'. For each sentence: 1) Present the English version, 2) Translate it into {profile['native']}, and 3) Ask the learner to repeat the sentence aloud. Wait for the learner’s response before presenting the next sentence."})

        history = [msg for msg in user_histories[user_id][-10:] if msg.get("content")]
        messages = [
            {"role": "system", "content": system_prompt}
        ]
        if mode == "pronunciation":
            messages.append({
    "role": "user",
    "content": f"The learner said: '{user_input}'. Please carefully analyze the pronunciation word-by-word.
- ✅ Clear if the pronunciation is accurate.
- ⚠️ Needs improvement if the word was unclear, distorted, or incorrect.
Give honest and strict evaluation. If more than 2 words are not clear, ask the learner to try again."
})
        else:
            messages.append({"role": "user", "content": f"Please start an English lesson using the topic '{user_topics[user_id]}'. First, introduce 5 to 10 vocabulary words in {profile['target']} with translations in {profile['native']}. After listing the vocabulary, say: '각 단어를 읽어보시고 준비가 되면 녹음하여 전송 해주세요.' Do not include additional instructions or explanations. After the learner finishes reading and pronouncing all vocabulary words, then and only then, continue by providing 3 to 5 example sentences related to the topic. For each sentence: 1) Present the English version, 2) Translate it into {profile['native']}, and 3) Ask the learner to repeat the sentence aloud. Wait for the learner’s response before presenting the next sentence. Maintain all explanations in {profile['native']} and examples in {profile['target']}."})
        messages += history

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
