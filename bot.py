import os
import openai
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters
from pydub import AudioSegment

user_profiles = {}
user_states = {}
user_topics = {}
user_vocab_sets = {}
user_vocab_index = {}
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

def get_system_prompt(profile):
    return f"""
You are a friendly English tutor. All explanations must be in English.
Speak slowly. Always reply in this structure:
1. Vocabulary Phase:
- Give 5 topic-related words. Format: word - meaning
- Ask learner to repeat
- Wait for learner audio and provide feedback
- Only use English word as feedback. Ex: coffee: good, map: say again: map, map

2. After 10 words are completed, present sentences:
- One sentence at a time (with native translation)
- Ask learner to repeat and send audio
- Provide pronunciation feedback
- Only then move to next sentence

Always respond with both text and voice (TTS). Never skip audio reply.
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
        await update.message.reply_text("✅ 설문 완료! 이제 수업을 시작할게요.\n무슨 주제로 수업을 시작할까요?")
        del user_states[user_id]

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
        await update.message.reply_text("먼저 /start 로 설문을 완료해주세요!")
        return

    user_topics[user_id] = text
    user_vocab_index[user_id] = 0
    user_sentence_index[user_id] = 0
    await generate_vocab_set(update, user_id)

async def generate_vocab_set(update, user_id):
    profile = user_profiles[user_id]
    topic = user_topics[user_id]
    current_set = user_vocab_index[user_id]
    system_prompt = get_system_prompt(profile)

    response = openai.chat.completions.create(
        model="gpt-3.5-turbo",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"Please provide Set {current_set+1} with 5 English vocabulary words for the topic '{topic}', with Korean meanings. Format: English - Korean"}
        ]
    )
    content = response.choices[0].message.content
    user_vocab_sets.setdefault(user_id, []).append(content)
    await update.message.reply_text(f"📘 단어들을 하나씩 따라 말해볼까요?\n{content}\n\n🗣 따라 말해보고, 준비가 되면 녹음해서 보내주세요!")

async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in user_profiles:
        await update.message.reply_text("먼저 /start 로 설문을 완료해주세요!")
        return

    file = await context.bot.get_file(update.message.voice.file_id)
    ogg_path = "voice.ogg"
    mp3_path = "voice.mp3"
    await file.download_to_drive(ogg_path)
    AudioSegment.from_ogg(ogg_path).export(mp3_path, format="mp3")

    with open(mp3_path, "rb") as f:
        transcript = openai.audio.transcriptions.create(model="whisper-1", file=f)
    user_input = transcript.text

    if user_vocab_index[user_id] < 2:
        await tutor_feedback(update, user_id, user_input, phase="vocab")
    else:
        await tutor_feedback(update, user_id, user_input, phase="sentence")

async def tutor_feedback(update, user_id, user_input, phase):
    system_msg = "You are an English pronunciation coach. Respond in English only."
    if phase == "vocab":
        prompt = f"The learner said: {user_input}. Give feedback in format: word: good OR word: say again: word, word"
        user_vocab_feedback.setdefault(user_id, []).append(user_input)
    else:
        sentence = user_sentences[user_id][user_sentence_index[user_id]]
        prompt = f"The learner said: {user_input}. Please evaluate this sentence: '{sentence}'. Use simple English."

    response = openai.chat.completions.create(
        model="gpt-3.5-turbo",
        messages=[{"role": "system", "content": system_msg}, {"role": "user", "content": prompt}]
    )
    feedback = response.choices[0].message.content
    await update.message.reply_text(f"📣 발음 피드백:\n{feedback}")

    # 음성도 함께 전송
    speech = openai.audio.speech.create(model="tts-1", voice="nova", input=feedback)
    with open("response.mp3", "wb") as f:
        f.write(speech.content)
    await update.message.reply_voice(voice=open("response.mp3", "rb"))

    if phase == "vocab":
        if len(user_vocab_feedback[user_id]) % 5 == 0:
            user_vocab_index[user_id] += 1
            if user_vocab_index[user_id] < 2:
                await generate_vocab_set(update, user_id)
            else:
                await generate_sentences(update, user_id)
        else:
            await update.message.reply_text("👂 다른 단어도 따라 말해보세요!")
    else:
        user_sentence_index[user_id] += 1
        await present_next_sentence(update, user_id)

async def generate_sentences(update, user_id):
    profile = user_profiles[user_id]
    topic = user_topics[user_id]
    system_prompt = get_system_prompt(profile)
    response = openai.chat.completions.create(
        model="gpt-3.5-turbo",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"Provide 3 English sentences about '{topic}' with Korean translation. Format: 1. English\nKorean"}
        ]
    )
    content = response.choices[0].message.content
    user_sentences[user_id] = content.split("\n\n")
    await present_next_sentence(update, user_id)

async def present_next_sentence(update, user_id):
    idx = user_sentence_index[user_id]
    if idx < len(user_sentences[user_id]):
        sentence = user_sentences[user_id][idx]
        await update.message.reply_text(f"🗣 문장 {idx+1}번입니다:\n{sentence}\n\n이 문장을 따라 말해보고, 준비되면 녹음해서 보내주세요!")
    else:
        await update.message.reply_text("🎉 오늘의 수업이 완료되었습니다! 수고하셨어요.")

if __name__ == "__main__":
    openai.api_key = os.getenv("OPENAI_API_KEY")
    app = ApplicationBuilder().token(os.getenv("TELEGRAM_TOKEN")).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_handler(MessageHandler(filters.VOICE, handle_voice))
    print("✅ CC4AI 튜터 작동 중")
    app.run_polling()
