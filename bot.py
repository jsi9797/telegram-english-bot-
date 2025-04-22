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
vocab_feedback_round = {}
current_vocab_list = {}
current_vocab_index = {}
sentence_index = {}
sentence_list = {}

survey_questions = [
    ("native", "🗣 모국어가 무엇인가요? (Your native language)?"),
    ("target", "📘 배우고 싶은 언어는 무엇인가요? (Which language would you like to learn?)"),
    ("age", "📅 나이대가 어떻게 되나요? (What is your age group?)"),
    ("gender", "👤 성별이 어떻게 되시나요? (남성/여성)"),
    ("level", "📊 현재 실력은 어느정도인가요? (Your level: beginner/intermediate?)")
]

def get_system_prompt(profile):
    level = profile.get("level", "beginner").lower()
    return f"""
You are a friendly, patient English tutor. The learner is {level} level.
Use {profile['native']} to explain and {profile['target']} to teach examples.
1. Begin with 10 vocabulary words related to the topic '{user_topics.get(profile['user_id'], 'hobby')}'
2. Present them in two sets of 5. Wait for user audio and give simple feedback like:
   computer: good / painting: say again: painting, painting
3. Only after all words are practiced correctly, present 3 sentences, one at a time.
4. Each sentence includes:
   - English
   - {profile['native']} translation
   - Prompt: "이 문장을 따라 말해보고, 준비가 되면 녹음해서 보내주세요!"
5. Wait for user voice, then provide simple sentence-level pronunciation feedback.
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
        del user_states[user_id]
        user_phases[user_id] = "waiting_topic"
        await update.message.reply_text("✅ 설문 완료! 이제 수업을 시작할게요.\n무슨 주제로 수업을 시작할까요?")

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text.strip()

    if user_id in user_states:
        state = user_states[user_id]
        key, _ = survey_questions[state]
        user_profiles[user_id][key] = text
        user_states[user_id] += 1
        await ask_next_question(update, user_id)
        return

    if user_id not in user_profiles or "level" not in user_profiles[user_id]:
        await update.message.reply_text("설문을 먼저 완료해주세요! /start")
        return

    if user_phases.get(user_id) == "waiting_topic":
        user_topics[user_id] = text
        user_phases[user_id] = "vocab"
        current_vocab_index[user_id] = 0
        vocab_feedback_round[user_id] = 0
        await generate_vocab(update, user_id)
    else:
        await update.message.reply_text("🎙 먼저 단어를 연습하고 피드백을 받아야 문장으로 넘어갈 수 있어요!")

async def generate_vocab(update, user_id):
    profile = user_profiles[user_id]
    profile["user_id"] = user_id
    system_prompt = get_system_prompt(profile)

    response = openai.chat.completions.create(
        model="gpt-3.5-turbo",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"Please give me 10 vocabulary words related to the topic '{user_topics[user_id]}'. Format: word - native meaning"}
        ]
    )

    vocab_text = response.choices[0].message.content
    vocab_lines = [line.strip() for line in vocab_text.split("\n") if line.strip()]
    current_vocab_list[user_id] = vocab_lines
    await send_vocab_set(update, user_id)

async def send_vocab_set(update, user_id):
    index = current_vocab_index[user_id]
    vocab_set = current_vocab_list[user_id][index:index+5]
    numbered = [f"{i+1}. {word}" for i, word in enumerate(vocab_set)]
    await update.message.reply_text("📘 단어들을 하나씩 따라 말해볼까요?\n\n" + "\n".join(numbered) + "\n\n🗣 따라 말해보고, 준비가 되면 녹음해서 보내주세요!")

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

    phase = user_phases.get(user_id, "vocab")

    if phase == "vocab":
        await handle_vocab_pronunciation(update, user_id, user_input)
    elif phase == "sentence":
        await handle_sentence_pronunciation(update, user_id, user_input)

async def handle_vocab_pronunciation(update, user_id, text):
    vocab_set = current_vocab_list[user_id][current_vocab_index[user_id]:current_vocab_index[user_id]+5]
    words = [line.split("-")[0].strip() for line in vocab_set]
    prompt = f"The learner said: {text}. Please give simple word-by-word pronunciation feedback ONLY using English vocabulary words like:\ncomputer: good\nmonitor: say again: monitor, monitor\nUse only these words: {', '.join(words)}"

    response = openai.chat.completions.create(
        model="gpt-3.5-turbo",
        messages=[
            {"role": "system", "content": "You are a pronunciation tutor for beginners. Keep feedback short and simple."},
            {"role": "user", "content": prompt}
        ]
    )

    feedback = response.choices[0].message.content
    await update.message.reply_text("📣 발음 피드백:\n" + feedback)

    if "say again" in feedback and vocab_feedback_round[user_id] < 1:
        vocab_feedback_round[user_id] += 1
        await update.message.reply_text("🎯 틀린 단어를 다시 한 번 따라 말해보세요! 제가 다시 확인해드릴게요.")
    else:
        current_vocab_index[user_id] += 5
        vocab_feedback_round[user_id] = 0
        if current_vocab_index[user_id] >= 10:
            user_phases[user_id] = "sentence"
            sentence_index[user_id] = 0
            await generate_sentences(update, user_id)
        else:
            await send_vocab_set(update, user_id)

async def generate_sentences(update, user_id):
    profile = user_profiles[user_id]
    system_prompt = get_system_prompt(profile)

    response = openai.chat.completions.create(
        model="gpt-3.5-turbo",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"Please provide 3 simple English sentences about '{user_topics[user_id]}'. Each with translation in {profile['native']}. Format: 1. ENGLISH\nNATIVE" }
        ]
    )

    sentences = [s for s in response.choices[0].message.content.split("\n") if s.strip()]
    sentence_list[user_id] = sentences
    await send_next_sentence(update, user_id)

async def send_next_sentence(update, user_id):
    idx = sentence_index.get(user_id, 0)
    if idx < len(sentence_list[user_id]):
        await update.message.reply_text(f"🗣 문장 {idx+1}번입니다:\n{sentence_list[user_id][idx]}\n\n🎙 이 문장을 따라 말해보고, 준비되면 녹음해서 보내주세요!")
    else:
        await update.message.reply_text("🎉 오늘의 문장 연습을 모두 마쳤어요! 정말 잘하셨어요!")

async def handle_sentence_pronunciation(update, user_id, text):
    sentence = sentence_list[user_id][sentence_index[user_id]]
    prompt = f"The learner said: {text}. Target sentence: '{sentence}'. Give short, simple feedback for beginners. Highlight mispronounced words, and say them twice like: 'travel, travel'."

    response = openai.chat.completions.create(
        model="gpt-3.5-turbo",
        messages=[
            {"role": "system", "content": "You are a pronunciation tutor for beginners. Feedback must be short and clear."},
            {"role": "user", "content": prompt}
        ]
    )

    reply = response.choices[0].message.content
    await update.message.reply_text("🗣 발음 피드백:\n" + reply)
    sentence_index[user_id] += 1
    await send_next_sentence(update, user_id)

if __name__ == "__main__":
    openai.api_key = os.getenv("OPENAI_API_KEY")
    app = ApplicationBuilder().token(os.getenv("TELEGRAM_TOKEN")).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_handler(MessageHandler(filters.VOICE, handle_voice))
    print("✅ CC4AI 튜터 작동 중")
    app.run_polling()
