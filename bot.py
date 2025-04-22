import os
import openai
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters
from pydub import AudioSegment
import random

user_profiles = {}
user_states = {}
user_histories = {}
user_topics = {}
user_phases = {}
user_vocab_sets = {}
user_vocab_feedback_done = {}
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
    level_input = profile.get("level", "beginner").lower()
    level = "intermediate" if "중급" in level_input else "beginner" if "초급" in level_input else level_input
    return f"""
You are a friendly, patient English tutor. The learner is {level} level.
Use {profile['native']} to explain and {profile['target']} to teach examples.
Start with 10 vocabulary words (5 per set), give pronunciation feedback like:
"coffee: good", "latte: say again: latte, latte".
After 10 words are completed correctly, move to sentence training.
Provide one sentence at a time: English + translation.
Ask the learner to repeat. Give feedback. Then show the next.
Wait for learner’s voice before continuing.
Always reply with both voice and text.
Do not switch to Korean instruction mode.
"""

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_states[user_id] = 0
    user_profiles[user_id] = {}
    user_phases[user_id] = "survey"
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

    if user_id in user_states:  # 설문 진행 중
        state = user_states[user_id]
        key, _ = survey_questions[state]
        user_profiles[user_id][key] = text
        user_states[user_id] += 1
        await ask_next_question(update, user_id)
        return

    if user_phases.get(user_id) == "waiting_topic":
        user_topics[user_id] = text
        user_vocab_sets[user_id] = [[], []]
        user_vocab_feedback_done[user_id] = [False, False]
        user_phases[user_id] = "vocab_1"
        await generate_vocab(update, user_id, set_num=0)
    else:
        await update.message.reply_text("🎤 음성으로 단어를 따라 말해주시고, 피드백을 받은 뒤 문장으로 넘어갈게요!")

async def generate_vocab(update, user_id, set_num=0):
    topic = user_topics[user_id]
    profile = user_profiles[user_id]
    system_prompt = get_system_prompt(profile)

    response = openai.chat.completions.create(
        model="gpt-3.5-turbo",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"Please give a list of 5 vocabulary words related to '{topic}', format: word - meaning in {profile['native']}."}
        ]
    )
    words = response.choices[0].message.content.strip()
    user_vocab_sets[user_id][set_num] = words
    await update.message.reply_text(f"📘 Set {set_num+1}:\n{words}\n\n🗣 단어를 하나씩 따라 말해보고, 준비되면 녹음해서 보내주세요!")

async def generate_sentences(update, user_id):
    profile = user_profiles[user_id]
    system_prompt = get_system_prompt(profile)
    topic = user_topics[user_id]

    response = openai.chat.completions.create(
        model="gpt-3.5-turbo",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"Please give 3 simple sentences using the topic '{topic}' with {profile['native']} translation. Format:\n1. 영어문장\n번역"}
        ]
    )
    content = response.choices[0].message.content.strip()
    sentences = content.split("\n\n")
    user_sentences[user_id] = sentences
    user_sentence_index[user_id] = 0
    await present_sentence(update, user_id)

async def present_sentence(update, user_id):
    idx = user_sentence_index[user_id]
    if idx < len(user_sentences[user_id]):
        sentence = user_sentences[user_id][idx]
        await update.message.reply_text(f"🧾 문장 {idx+1}입니다:\n{sentence}\n\n🎤 이 문장을 따라 말해보고, 준비되면 녹음해서 보내주세요!")
    else:
        await update.message.reply_text("🎉 오늘의 수업이 완료되었습니다! 수고하셨어요.")

async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    phase = user_phases.get(user_id, "")

    file = await context.bot.get_file(update.message.voice.file_id)
    ogg_path = "voice.ogg"
    mp3_path = "voice.mp3"
    await file.download_to_drive(ogg_path)
    AudioSegment.from_ogg(ogg_path).export(mp3_path, format="mp3")
    with open(mp3_path, "rb") as f:
        transcript = openai.audio.transcriptions.create(model="whisper-1", file=f)
    user_input = transcript.text.strip()

    # 음성 분석 요청
    await tutor_feedback(update, user_id, user_input)

async def tutor_feedback(update, user_id, user_input):
    phase = user_phases[user_id]
    profile = user_profiles[user_id]
    system_prompt = get_system_prompt(profile)

    if phase.startswith("vocab"):
        set_num = 0 if phase == "vocab_1" else 1
        vocab_text = user_vocab_sets[user_id][set_num]
        prompt = f"""The learner said: "{user_input}".
Please check pronunciation of the following words one by one.
Respond simply like:
"coffee: good", or "latte: say again: latte, latte".
Target words:\n{vocab_text}"""

        user_vocab_feedback_done[user_id][set_num] = True

    elif phase == "sentence":
        idx = user_sentence_index[user_id]
        target = user_sentences[user_id][idx]
        prompt = f"""The learner said: "{user_input}".
Target sentence: "{target}".
Please check their pronunciation and respond simply and clearly.
If accurate, say "Good job!" and move to next. If not, ask to repeat.
"""

    else:
        await update.message.reply_text("⚠️ 수업 상태가 초기화되었어요. /start 로 다시 시작해주세요.")
        return

    response = openai.chat.completions.create(
        model="gpt-3.5-turbo",
        messages=[
            {"role": "system", "content": "You are a pronunciation tutor. Provide simple English-based feedback. No Korean."},
            {"role": "user", "content": prompt}
        ]
    )
    reply = response.choices[0].message.content.strip()
    await update.message.reply_text("📣 발음 피드백:\n" + reply)

    speech = openai.audio.speech.create(model="tts-1", voice="nova", input=reply)
    tts_path = "response.mp3"
    with open(tts_path, "wb") as f:
        f.write(speech.content)
    await update.message.reply_voice(voice=open(tts_path, "rb"))

    if phase == "vocab_1" and user_vocab_feedback_done[user_id][0]:
        user_phases[user_id] = "vocab_2"
        await generate_vocab(update, user_id, set_num=1)
    elif phase == "vocab_2" and user_vocab_feedback_done[user_id][1]:
        user_phases[user_id] = "sentence"
        await generate_sentences(update, user_id)
    elif phase == "sentence":
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
