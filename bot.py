import os
import openai
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters
from pydub import AudioSegment

user_profiles = {}
user_states = {}
user_histories = {}
user_topics = {}
user_vocab = {}
user_vocab_done = {}
user_sentences = {}
user_sent_idx = {}

survey_questions = [
    ("native", "🗣 모국어가 무엇인가요? (Your native language)?"),
    ("target", "📘 배우고 싶은 언어는 무엇인가요? (Which language would you like to learn?)"),
    ("age", "📅 나이대가 어떻게 되나요? (What is your age group?)"),
    ("gender", "👤 성별이 어떻게 되시나요? (남성/여성)"),
    ("level", "📊 현재 실력은 어느정도인가요? (Your level: beginner/intermediate?)")
]

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

    if user_id not in user_profiles or "level" not in user_profiles[user_id]:
        if user_id not in user_states:
            user_states[user_id] = 0
            user_profiles[user_id] = {}
            await update.message.reply_text("👋 설문을 시작합니다!")
        state = user_states[user_id]
        key, _ = survey_questions[state]
        user_profiles[user_id][key] = text
        user_states[user_id] += 1
        await ask_next_question(update, user_id)
        return

    if user_id not in user_topics:
        user_topics[user_id] = text
        # 예시 단어와 문장 (하드코딩된 예시)
        vocab_list = ["computer", "keyboard", "monitor", "mouse", "internet"]
        sentences = [
            "I use my computer to browse the internet.",
            "The monitor is very bright.",
            "I need a new keyboard for work."
        ]
        user_vocab[user_id] = vocab_list
        user_sentences[user_id] = sentences
        user_sent_idx[user_id] = 0
        user_vocab_done[user_id] = False
        await update.message.reply_text("좋아요. 단어들을 하나씩 따라 말해볼까요?\n")
        for idx, word in enumerate(vocab_list, 1):
            await update.message.reply_text(f"{idx}. {word}")
        await update.message.reply_text("✏️ 위 단어들을 한번씩 따라 말해보고, 준비가 되면 녹음하여 전송해주세요!")
        return

    await update.message.reply_text("✋ 음성으로 단어를 따라 말해주시고, 발음 피드백을 받으면 문장 학습으로 넘어가요!")

async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in user_profiles or user_id not in user_topics:
        await update.message.reply_text("먼저 설문을 완료하고 수업 주제를 입력해주세요.")
        return

    file = await context.bot.get_file(update.message.voice.file_id)
    ogg_path = "voice.ogg"
    mp3_path = "voice.mp3"
    await file.download_to_drive(ogg_path)
    AudioSegment.from_ogg(ogg_path).export(mp3_path, format="mp3")

    with open(mp3_path, "rb") as f:
        transcript = openai.audio.transcriptions.create(model="whisper-1", file=f)

    text = transcript.text.strip()
    await update.message.reply_text(f"🎧 인식된 발화: {text}")

    # 발음 피드백 요청
    feedback = openai.chat.completions.create(
        model="gpt-3.5-turbo",
        messages=[
            {"role": "system", "content": "You are a strict pronunciation coach. Give honest feedback on each word's clarity."},
            {"role": "user", "content": f"The learner said: '{text}'. Please give feedback on each word."}
        ]
    ).choices[0].message.content

    await update.message.reply_text(f"🗣️ 발음 피드백:\n{feedback}")

    # 단어 학습 완료 여부
    if not user_vocab_done[user_id]:
        user_vocab_done[user_id] = True
        await update.message.reply_text("✅ 단어 학습을 마쳤어요. 이제 문장 학습으로 넘어갈게요.")
        await send_next_sentence(update, user_id)
        return

    # 문장 학습
    await update.message.reply_text("잘 들었어요! 계속해서 문장 학습을 이어갈게요.")
    await send_next_sentence(update, user_id)

async def send_next_sentence(update, user_id):
    idx = user_sent_idx[user_id]
    sentences = user_sentences[user_id]
    if idx >= len(sentences):
        await update.message.reply_text("🎉 모든 문장을 완료했어요! 이제 배운 문장을 응용해볼까요?")
        return
    sentence = sentences[idx]
    await update.message.reply_text(f"{idx+1}. {sentence}\n이 문장을 한번 따라 말해보고, 준비가 되면 녹음하여 전송해주세요!")
    user_sent_idx[user_id] += 1

if __name__ == "__main__":
    openai.api_key = os.getenv("OPENAI_API_KEY")
    app = ApplicationBuilder().token(os.getenv("TELEGRAM_TOKEN")).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_handler(MessageHandler(filters.VOICE, handle_voice))
    print("✅ CC4AI 튜터 작동 중")
    app.run_polling()
