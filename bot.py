import os
import openai
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters
from pydub import AudioSegment

user_profiles = {}
user_states = {}
user_histories = {}
user_topics = {}
user_vocab_done = {}
user_sentences = {}
user_sentence_index = {}

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
        del user_states[user_id]
        await update.message.reply_text("✅ 설문 완료! 이제 수업을 시작할게요 형님.")
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

    if user_id not in user_topics:
        user_topics[user_id] = text
        await update.message.reply_text("🧠 단어 학습부터 시작할게요. 아래 단어들을 따라 읽어보세요:")

        vocab_list = [
            ("computer", "컴퓨터"),
            ("internet", "인터넷"),
            ("keyboard", "키보드"),
            ("monitor", "모니터"),
            ("email", "이메일")
        ]
        user_profiles[user_id]["vocab_list"] = vocab_list
        user_vocab_done[user_id] = False
        user_sentence_index[user_id] = 0
        user_sentences[user_id] = [
            ("I use my computer to browse the internet.", "인터넷을 둘러보기 위해서 컴퓨터를 사용해요."),
            ("I need a keyboard and a mouse to type.", "타이핑을 하려면 키보드와 마우스가 필요해요."),
            ("The monitor is too bright.", "모니터가 너무 밝아요."),
            ("I received an important email this morning.", "오늘 아침에 중요한 이메일을 받았어요.")
        ]

        for en, ko in vocab_list:
            await update.message.reply_text(f"{en} - {ko}")
        await update.message.reply_text("🗣 각 단어를 읽어보시고 준비가 되면 녹음하여 전송해주세요.")
        return

    if user_vocab_done.get(user_id, False):
        await update.message.reply_text("🎯 이미 단어 학습이 완료되었습니다. 문장 발음을 들려주세요!")
    else:
        await update.message.reply_text("📚 단어 발음 먼저 완료해주세요!")

async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    file = await context.bot.get_file(update.message.voice.file_id)
    ogg_path = "voice.ogg"
    mp3_path = "voice.mp3"
    await file.download_to_drive(ogg_path)
    AudioSegment.from_ogg(ogg_path).export(mp3_path, format="mp3")

    with open(mp3_path, "rb") as f:
        transcript = openai.audio.transcriptions.create(model="whisper-1", file=f)
    text = transcript.text

    if not user_vocab_done.get(user_id, False):
        user_vocab_done[user_id] = True
        await update.message.reply_text("✅ 단어 발음 확인 완료! 이제 문장 학습으로 넘어갈게요.")
        await send_next_sentence(update, user_id)
    else:
        await evaluate_sentence(update, user_id, text)

async def send_next_sentence(update, user_id):
    idx = user_sentence_index[user_id]
    if idx < len(user_sentences[user_id]):
        en, ko = user_sentences[user_id][idx]
        await update.message.reply_text(f"📝 문장 {idx+1}: {en}
한국어: {ko}")
        await update.message.reply_text("이 문장을 한번 따라 말해보고, 준비가 되면 녹음하여 전송해주세요!")
    else:
        await update.message.reply_text("🎉 수업이 끝났습니다! 다음에 또 만나요.")

async def evaluate_sentence(update, user_id, user_text):
    idx = user_sentence_index[user_id]
    target_en, _ = user_sentences[user_id][idx]
    user_sentence_index[user_id] += 1

    messages = [
        {"role": "system", "content": "You are an English pronunciation evaluator. Give clear, brief feedback."},
        {"role": "user", "content": f"The learner tried to say: '{user_text}'\nThe target sentence was: '{target_en}'\nPlease give pronunciation tips in Korean and encourage retry only if really needed."}
    ]

    response = openai.chat.completions.create(model="gpt-3.5-turbo", messages=messages)
    reply = response.choices[0].message.content
    await update.message.reply_text(reply)

    await send_next_sentence(update, user_id)

if __name__ == "__main__":
    openai.api_key = os.getenv("OPENAI_API_KEY")
    app = ApplicationBuilder().token(os.getenv("TELEGRAM_TOKEN")).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_handler(MessageHandler(filters.VOICE, handle_voice))
    print("✅ CC4AI 튜터 작동 중")
    app.run_polling()

