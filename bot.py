import os
import openai
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters
from pydub import AudioSegment

user_profiles = {}
user_states = {}
user_histories = {}
user_topics = {}
user_phases = {}
user_vocab_list = {}
user_sentences = {}
user_sentence_index = {}

survey_questions = [
    ("native", "🗣 모국어가 무엇인가요? (Your native language)?"),
    ("target", "📘 배우고 싶은 언어는 무엇인가요? (Which language would you like to learn?)"),
    ("age", "📅 나이대가 어떻게 되나요? (What is your age group?)"),
    ("gender", "👤 성별이 어떻게 되시나요? (남성/여성)"),
    ("level", "📊 현재 실력은 어느정도인가요? (Your level: beginner/intermediate?)")
]

def get_system_prompt(profile):
    return f"""
You are a friendly, patient English tutor. The learner is {profile['level']} level.
Only teach English. Do not explain in Korean or any other language.
Speak slowly and clearly. Give feedback in English only.
Step-by-step structure:
1. Present 5 topic-related vocabulary words (English only).
2. Ask the learner to repeat them aloud. Wait for audio.
3. Give simple feedback like:
   - "hope: good"
   - "decision: say again: decision, decision"
4. After 5 words, repeat with 5 more words (total 10).
5. When pronunciation is complete, present 1 sentence at a time:
   - English sentence + native translation
   - Prompt user to repeat aloud
   - Wait for recording and give feedback
   - Only then, proceed to next sentence
Keep it interactive, gentle, and clear.
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
        del user_states[user_id]
        user_phases[user_id] = "waiting_topic"
        await update.message.reply_text("✅ 설문 완료! 이제 수업을 시작할게요.\n무슨 주제로 수업을 시작할까요?")

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text.strip()

    if user_id in user_states:  # 설문 중
        state = user_states[user_id]
        key, _ = survey_questions[state]
        user_profiles[user_id][key] = text
        user_states[user_id] += 1
        await ask_next_question(update, user_id)
        return

    if user_id not in user_profiles or "level" not in user_profiles[user_id]:
        await update.message.reply_text("설문부터 먼저 진행해주세요! /start")
        return

    if user_phases.get(user_id) == "waiting_topic":
        user_topics[user_id] = text
        user_histories[user_id] = []
        user_phases[user_id] = "vocab"
        user_vocab_list[user_id] = []
        user_sentence_index[user_id] = 0
        await generate_vocab(update, user_id)
    else:
        await update.message.reply_text("음성으로 단어를 말해주세요. 발음 피드백을 받은 후 문장 학습으로 넘어가요!")

async def generate_vocab(update, user_id):
    profile = user_profiles[user_id]
    system_prompt = get_system_prompt(profile)

    response = openai.chat.completions.create(
        model="gpt-3.5-turbo",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"Please give 10 English vocabulary words related to '{user_topics[user_id]}', each with a simple translation in {profile['native']}. Format like: word - meaning"}
        ]
    )
    vocab = response.choices[0].message.content
    lines = [line for line in vocab.split("\n") if line.strip()]
    user_vocab_list[user_id] = lines
    first_batch = lines[:5]

    await update.message.reply_text("🗣 단어들을 하나씩 따라 말해볼까요?\n" + "\n".join(first_batch) + "\n\n🎙 따라 말해보고, 준비가 되면 녹음해서 보내주세요!")

async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    file = await context.bot.get_file(update.message.voice.file_id)
    ogg_path = "voice.ogg"
    mp3_path = "voice.mp3"
    await file.download_to_drive(ogg_path)
    AudioSegment.from_ogg(ogg_path).export(mp3_path, format="mp3")

    with open(mp3_path, "rb") as f:
        transcript = openai.audio.transcriptions.create(model="whisper-1", file=f)

    user_input = transcript.text
    await tutor_feedback(update, user_id, user_input)

async def tutor_feedback(update: Update, user_id, user_input: str):
    profile = user_profiles[user_id]
    phase = user_phases.get(user_id, "vocab")
    system_prompt = get_system_prompt(profile)

    if phase == "vocab":
        prompt = f"The learner said: {user_input}. Please give very simple pronunciation feedback word-by-word. Use only English words and this format:\nhope: good\ngardening: say again: gardening, gardening"
    else:
        prompt = f"The learner said: {user_input}. Give beginner-friendly feedback on this sentence. Suggest corrections in simple terms. Do not explain Korean. Provide only English sentence feedback."

    response = openai.chat.completions.create(
        model="gpt-3.5-turbo",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt}
        ]
    )
    reply = response.choices[0].message.content
    await update.message.reply_text("📣 발음 피드백:\n" + reply)

    speech = openai.audio.speech.create(
        model="tts-1",
        voice="nova",
        input=reply
    )
    tts_path = "voice.mp3"
    with open(tts_path, "wb") as f:
        f.write(speech.content)
    await update.message.reply_voice(voice=open(tts_path, "rb"))

    if phase == "vocab":
        if len(user_vocab_list[user_id]) > 5:
            next_batch = user_vocab_list[user_id][5:]
            user_vocab_list[user_id] = []
            await update.message.reply_text("🗣 다음 단어들도 연습해볼까요?\n" + "\n".join(next_batch) + "\n\n🎙 따라 말해보고 준비되면 녹음해주세요!")
        else:
            user_phases[user_id] = "sentence"
            await generate_sentences(update, user_id)
    else:
        await present_next_sentence(update, user_id)

async def generate_sentences(update, user_id):
    profile = user_profiles[user_id]
    system_prompt = get_system_prompt(profile)

    response = openai.chat.completions.create(
        model="gpt-3.5-turbo",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"Please provide 3 English example sentences related to '{user_topics[user_id]}'. Include translations in {profile['native']}. Format:\n1. Sentence\nTranslation"}
        ]
    )
    sentences = [s for s in response.choices[0].message.content.split("\n\n") if s.strip()]
    user_sentences[user_id] = sentences
    user_sentence_index[user_id] = 0
    await present_next_sentence(update, user_id)

async def present_next_sentence(update, user_id):
    index = user_sentence_index[user_id]
    if index < len(user_sentences[user_id]):
        sentence = user_sentences[user_id][index]
        await update.message.reply_text(f"📗 문장 {index+1}번입니다:\n{sentence}\n\n🗣 이 문장을 따라 말해보고, 준비되면 녹음해서 보내주세요!")
    else:
        await update.message.reply_text("🎉 오늘 배운 문장을 모두 연습했어요! 수고하셨습니다.")

if __name__ == "__main__":
    openai.api_key = os.getenv("OPENAI_API_KEY")
    app = ApplicationBuilder().token(os.getenv("TELEGRAM_TOKEN")).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_handler(MessageHandler(filters.VOICE, handle_voice))
    print("✅ CC4AI 튜터 작동 중")
    app.run_polling()
