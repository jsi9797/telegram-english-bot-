import os
import openai
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters
from pydub import AudioSegment
import random

user_profiles = {}
user_states = {}
user_topics = {}
user_phases = {}
user_vocab_set = {}
user_vocab_feedback = {}
user_sentences = {}
user_sentence_index = {}

survey_questions = [
    ("native", "🗣 모국어가 무엇인가요? (Your native language)?"),
    ("target", "📘 배우고 싶은 언어는 무엇인가요? (Which language would you like to learn?)"),
    ("age", "📅 나이대가 어떻게 되나요? (What is your age group?)"),
    ("gender", "👤 성별이 어떻게 되시나요? (남성/여성)"),
    ("level", "📊 현재 실력은 어느정도인가요? (Your level: beginner/intermediate?)")
]

def normalize_level(level_text):
    return {
        "초급": "beginner",
        "중급": "intermediate",
        "고급": "advanced"
    }.get(level_text.lower(), level_text.lower())

def get_system_prompt(profile):
    level = normalize_level(profile.get("level", "beginner"))
    return f"""
You are a friendly, patient English tutor. The learner is {level} level.
Use {profile['native']} to explain and {profile['target']} to teach examples.
Begin by presenting 5 to 7 topic-related vocabulary words with their {profile['native']} meaning.
Ask the learner to repeat the words aloud and wait for pronunciation recording.
Provide simple, clear pronunciation feedback like: "computer: good", "monitor: say again: monitor, monitor".
Only after words are practiced, present one English sentence at a time:
- Show the English sentence + native translation
- Ask the learner to repeat it aloud
- After their voice, give pronunciation feedback
Keep the lesson interactive and in simple steps.
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
        await update.message.reply_text("설문을 먼저 완료해주세요! /start")
        return

    # 주제 입력
    if user_phases.get(user_id) == "waiting_topic":
        user_topics[user_id] = text
        user_vocab_set[user_id] = []
        user_vocab_feedback[user_id] = []
        user_sentence_index[user_id] = 0
        user_phases[user_id] = "vocab1"
        await generate_vocab(update, user_id, set_num=1)
    else:
        await update.message.reply_text("음성으로 단어를 따라 말해주시고, 발음 피드백을 받은 후 문장 학습으로 넘어가요!")

async def generate_vocab(update, user_id, set_num=1):
    topic = user_topics[user_id]
    profile = user_profiles[user_id]
    system_prompt = get_system_prompt(profile)

    response = openai.chat.completions.create(
        model="gpt-3.5-turbo",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"Give 5 different vocabulary words in English related to the topic '{topic}', with translations in {profile['native']}. Format: 1. airplane - 비행기"}
        ]
    )

    vocab_text = response.choices[0].message.content
    user_vocab_set[user_id].append(vocab_text)
    await update.message.reply_text(f"📘 단어들을 하나씩 따라 말해볼까요?\nSet {set_num}:\n{vocab_text}\n\n🗣 따라 말해보고, 준비가 되면 녹음해서 보내주세요!")

async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in user_profiles or "level" not in user_profiles[user_id]:
        await update.message.reply_text("먼저 설문을 완료해주세요! /start")
        return

    file = await context.bot.get_file(update.message.voice.file_id)
    ogg_path = "voice.ogg"
    mp3_path = "voice.mp3"
    await file.download_to_drive(ogg_path)
    AudioSegment.from_ogg(ogg_path).export(mp3_path, format="mp3")
    with open(mp3_path, "rb") as f:
        transcript = openai.audio.transcriptions.create(model="whisper-1", file=f)
    user_input = transcript.text

    phase = user_phases.get(user_id)
    if phase in ["vocab1", "vocab2"]:
        await tutor_feedback(update, user_id, user_input, phase)
    elif phase == "sentence":
        await sentence_feedback(update, user_id, user_input)

async def tutor_feedback(update, user_id, user_input, phase):
    profile = user_profiles[user_id]
    system_prompt = get_system_prompt(profile)

    prompt = f"The learner said: {user_input}. Please provide simple English-based pronunciation feedback like: coffee: good, latte: say again: latte, latte."

    await update.message.reply_text("📣 발음 피드백을 드릴게요!")

    response = openai.chat.completions.create(
        model="gpt-3.5-turbo",
        messages=[{"role": "system", "content": system_prompt},
                  {"role": "user", "content": prompt}]
    )

    feedback = response.choices[0].message.content
    user_vocab_feedback[user_id].append(feedback)
    await update.message.reply_text("📣 발음 피드백:\n" + feedback)

    if phase == "vocab1":
        user_phases[user_id] = "vocab2"
        await generate_vocab(update, user_id, set_num=2)
    else:
        user_phases[user_id] = "sentence"
        await generate_sentences(update, user_id)

async def generate_sentences(update, user_id):
    topic = user_topics[user_id]
    profile = user_profiles[user_id]
    system_prompt = get_system_prompt(profile)

    response = openai.chat.completions.create(
        model="gpt-3.5-turbo",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"Give 3 sentences in English related to the topic '{topic}' with {profile['native']} translations. Format: 1. 영어문장\n{profile['native']} 해석"}
        ]
    )

    sentences = response.choices[0].message.content.split("\n\n")
    user_sentences[user_id] = sentences
    await present_next_sentence(update, user_id)

async def present_next_sentence(update, user_id):
    index = user_sentence_index[user_id]
    if index < len(user_sentences[user_id]):
        await update.message.reply_text(f"📗 문장 {index+1}번입니다:\n{user_sentences[user_id][index]}\n\n🗣 이 문장을 따라 말해보고, 준비되면 녹음해서 보내주세요!")
    else:
        await update.message.reply_text("🎉 오늘 수업이 모두 완료되었습니다. 수고하셨어요!")

async def sentence_feedback(update, user_id, user_input):
    index = user_sentence_index[user_id]
    target = user_sentences[user_id][index]

    response = openai.chat.completions.create(
        model="gpt-3.5-turbo",
        messages=[
            {"role": "system", "content": "You are a strict but friendly pronunciation tutor."},
            {"role": "user", "content": f"The learner said: '{user_input}'. Please analyze and give brief feedback for this sentence:\n{target}"}
        ]
    )

    feedback = response.choices[0].message.content
    await update.message.reply_text("📣 발음 피드백:\n" + feedback)
    user_sentence_index[user_id] += 1
    await present_next_sentence(update, user_id)

if __name__ == "__main__":
    openai.api_key = os.getenv("OPENAI_API_KEY")
    app = ApplicationBuilder().token(os.getenv("TELEGRAM_TOKEN")).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_handler(MessageHandler(filters.VOICE, handle_voice))
    print("✅ CC4AI 튜터 작동 중")
    app.run_polling()
