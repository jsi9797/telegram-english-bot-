import os
import openai
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters
from pydub import AudioSegment

openai.api_key = os.getenv("OPENAI_API_KEY")

user_profiles = {}
user_states = {}
user_histories = {}

survey_questions = [
    ("name", "👤 이름이 어떻게 되시나요?"),
    ("native", "🗣 모국어가 무엇인가요? (예: 한국어, 일본어)"),
    ("target", "📘 배우고 싶은 언어는 무엇인가요? (예: 영어, 일본어)"),
    ("age", "📅 나이대가 어떻게 되시나요? (예: 20대, 30대, 40대, 50대 이상)"),
    ("gender", "👥 성별이 어떻게 되시나요? (남성/여성)"),
    ("level", "📊 실력은 어느정도인가요? (초급, 중급, 고급)")
]

language_explanation = {
    "한국어": "설명은 한국어로 해줘.",
    "일본어": "日本語で説明してください。",
    "스페인어": "Explica en español, por favor.",
    "중국어": "请用中文解释。",
    "인도네시아어": "Tolong jelaskan dalam Bahasa Indonesia."
}

def get_system_prompt(profile, history):
    native = profile.get("native", "")
    target = profile.get("target", "")
    name = profile.get("name", "")
    level = profile.get("level", "초급")
    explanation = language_explanation.get(native, "Explain in English.")
    language_mix = "많이" if level == "초급" else "조금" if level == "중급" else "거의 없이"

    history_lines = "\n".join(history[-5:]) if history else ""

    return f"""
You are a smart GPT tutor named CC4AI 튜터.
Your student's name is {name}님. Their native language is {native}, and they are learning {target}.
Explain things using their native language {language_mix}. When they make mistakes, kindly correct them with grammar, pronunciation, and better word choices.
Remember their past questions and keep a natural flow.

Recent chat:
{history_lines}

Start by asking a friendly question based on past responses if any.
If it's the first message, you can suggest a topic like "취미" or "오늘 하루".
"""

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_states[user_id] = 0
    user_profiles[user_id] = {}
    user_histories[user_id] = []
    await update.message.reply_text("👋 안녕하세요! 설문을 시작합니다.\n(※ 설문은 텍스트 입력만 가능해요)")
    await ask_next_question(update, user_id)

async def ask_next_question(update, user_id):
    state = user_states[user_id]
    if state < len(survey_questions):
        key, question = survey_questions[state]
        await update.message.reply_text(question)
    else:
        name = user_profiles[user_id].get("name", "학습자")
        await update.message.reply_text(f"✅ 설문 완료! {name}님, 이제 수업을 시작할게요.")
        del user_states[user_id]
        await tutor_response("수업을 시작하자", update, user_profiles[user_id])

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text.strip()

    if "설문조사 다시" in text:
        user_profiles[user_id] = {}
        user_states[user_id] = 0
        await update.message.reply_text("🔁 설문을 다시 시작할게요!")
        await ask_next_question(update, user_id)
        return

    if user_id in user_states:
        state = user_states[user_id]
        key, _ = survey_questions[state]
        user_profiles[user_id][key] = text
        user_states[user_id] += 1
        await ask_next_question(update, user_id)
    else:
        if user_id not in user_profiles:
            user_profiles[user_id] = {}
            user_states[user_id] = 0
            await update.message.reply_text("📋 설문 먼저 진행할게요.")
            await ask_next_question(update, user_id)
            return
        user_histories.setdefault(user_id, []).append(f"User: {text}")
        await tutor_response(text, update, user_profiles[user_id])

async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in user_profiles or user_id in user_states:
        await update.message.reply_text("📋 설문 완료 후에 음성 사용이 가능해요!")
        return

    file = await context.bot.get_file(update.message.voice.file_id)
    ogg_path = "voice.ogg"
    mp3_path = "voice.mp3"
    await file.download_to_drive(ogg_path)
    AudioSegment.from_ogg(ogg_path).export(mp3_path, format="mp3")

    with open(mp3_path, "rb") as f:
        transcript = openai.audio.transcriptions.create(model="whisper-1", file=f)

    user_histories.setdefault(user_id, []).append(f"User (voice): {transcript.text}")
    await tutor_response(transcript.text, update, user_profiles[user_id])

async def tutor_response(user_input: str, update: Update, profile: dict):
    user_id = update.effective_user.id
    system_prompt = get_system_prompt(profile, user_histories.get(user_id, []))

    try:
        response = openai.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_input}
            ]
        )
        reply = response.choices[0].message.content
        user_histories[user_id].append(f"Tutor: {reply}")
        await update.message.reply_text(reply)

        # 음성으로도 응답
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
    app = ApplicationBuilder().token(os.getenv("TELEGRAM_TOKEN")).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_handler(MessageHandler(filters.VOICE, handle_voice))
    print("✅ CC4AI 튜터 작동 중")
    app.run_polling()
