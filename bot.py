import os
import openai
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters
import requests
from pydub import AudioSegment

openai.api_key = os.getenv("OPENAI_API_KEY")
TOKEN = os.getenv("TELEGRAM_TOKEN")

user_profiles = {}
user_states = {}
user_histories = {}

survey_questions = [
    ("name", "이름이 무엇인가요? (What is your name?)"),
    ("native", "모국어가 무엇인가요? (Your native language)?"),
    ("target", "배우고 싶은 언어는 무엇인가요? (Which language would you like to learn?)"),
    ("age", "나이대가 어떻게 되시나요? (예: 20대, 30대, 40대 등)?"),
    ("gender", "성별이 어떻게 되시나요? (남성/여성)?"),
    ("level", "현재 실력은 어느정도인가요? (예: 초급, 중급, 고급 또는 설명)?")
]

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_profiles[user_id] = {}
    user_states[user_id] = 0
    await update.message.reply_text("📝 설문조사를 시작합니다! 텍스트로 입력해주세요.")
    await ask_next_question(update, user_id)

async def ask_next_question(update, user_id):
    state = user_states[user_id]
    if state < len(survey_questions):
        key, question = survey_questions[state]
        await update.message.reply_text(question)
    else:
        profile = user_profiles[user_id]
        name = profile.get("name", "학습자")
        user_histories[user_id] = []
        await update.message.reply_text(f"✅ 설문이 완료되었습니다. 이제 수업을 시작할게요 {name}님!")
        del user_states[user_id]
        await tutor_response("오늘 수업을 시작하겠습니다!", update, profile)

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text.strip()

    if "설문조사" in text:
        user_profiles[user_id] = {}
        user_states[user_id] = 0
        await update.message.reply_text("📝 설문조사를 다시 시작합니다.")
        await ask_next_question(update, user_id)
        return

    if user_id in user_states:
        state = user_states[user_id]
        key, _ = survey_questions[state]
        user_profiles[user_id][key] = text
        user_states[user_id] += 1
        await ask_next_question(update, user_id)
    else:
        profile = user_profiles.get(user_id)
        if profile:
            await tutor_response(text, update, profile)
        else:
            await start(update, context)

async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in user_profiles or user_id in user_states:
        await update.message.reply_text("음성은 설문 완료 후 사용하실 수 있어요. 먼저 설문을 완료해주세요.")
        return

    file = await context.bot.get_file(update.message.voice.file_id)
    ogg_path = "voice.ogg"
    mp3_path = "voice.mp3"
    await file.download_to_drive(ogg_path)
    AudioSegment.from_ogg(ogg_path).export(mp3_path, format="mp3")

    with open(mp3_path, "rb") as f:
        transcript = openai.audio.transcriptions.create(model="whisper-1", file=f)

    await tutor_response(transcript.text, update, user_profiles[user_id])

def get_system_prompt(profile):
    level = profile.get("level", "").lower()
    native = profile.get("native", "Korean")
    target = profile.get("target", "English")
    name = profile.get("name", "학습자")

    if "초급" in level:
        native_ratio = 0.9
    elif "중급" in level:
        native_ratio = 0.5
    else:
        native_ratio = 0.2

    return f"""
You are a smart GPT tutor for language learners.

The learner's name is {name}, native language is {native}, and target language is {target}.
Please explain using {int(native_ratio*100)}% native language and {int((1-native_ratio)*100)}% target language.

Teach through dialogue, but let the learner speak first.
Correct grammar, pronunciation (focus on R/L/TH/V etc.), and guide pronunciation.

If the learner says something related to a topic (e.g. 'computer'), continue the topic and teach grammar, vocab, and pronunciation based on that.

Remember previous utterances and avoid repeating yourself or changing topics unnaturally.
Always speak politely using {name}님, and avoid slang or childish tones.
"""

async def tutor_response(user_input: str, update: Update, profile: dict):
    user_id = update.effective_user.id
    system_prompt = get_system_prompt(profile)
    history = user_histories.get(user_id, [])

    messages = [{"role": "system", "content": system_prompt}]
    messages.extend(history[-5:])  # 최근 대화 5개 기억
    messages.append({"role": "user", "content": user_input})

    try:
        response = openai.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=messages
        )
        reply = response.choices[0].message.content
        user_histories.setdefault(user_id, []).append({"role": "user", "content": user_input})
        user_histories[user_id].append({"role": "assistant", "content": reply})

        await update.message.reply_text(reply)

        speech = openai.audio.speech.create(
            model="tts-1",
            voice="nova",
            input=reply
        )
        with open("response.mp3", "wb") as f:
            f.write(speech.content)
        await update.message.reply_voice(voice=open("response.mp3", "rb"))

    except Exception as e:
        await update.message.reply_text(f"❌ 오류 발생: {str(e)}")

if __name__ == "__main__":
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_handler(MessageHandler(filters.VOICE, handle_voice))
    print("✅ CC4AI 튜터 작동 중")
    app.run_polling()
