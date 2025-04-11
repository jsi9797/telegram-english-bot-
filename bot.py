import os
import openai
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters
import requests
from pydub import AudioSegment

openai.api_key = os.getenv("OPENAI_API_KEY")

# 사용자별 설정 저장용 딕셔너리
user_profiles = {}

# 언어별 설명 템플릿
language_explanation = {
    "Korean": "설명은 한국어로 해주세요.",
    "Japanese": "説明は日本語でお願いします。",
    "Spanish": "Explica en español, por favor.",
    "Vietnamese": "Giải thích bằng tiếng Việt giúp tôi.",
    "Chinese": "请用中文解释。",
    "Indonesian": "Tolong jelaskan dalam Bahasa Indonesia."
}

# 나이대별 톤 설정 함수
def get_tone(age, gender):
    if age == "20대":
        return "형" if gender == "남성" else "언니"
    elif age == "30대":
        return "형" if gender == "남성" else "언니"
    elif age == "40대":
        return "형님" if gender == "남성" else "언니"
    elif age == "50대 이상":
        return "형님" if gender == "남성" else "선생님"
    return "형님"

# 시스템 프롬프트 생성
def get_system_prompt(profile):
    explanation = language_explanation.get(profile['native'], "Explain in English.")
    tone = get_tone(profile['age'], profile['gender'])
    return f"""
You are a kind, smart, and responsive GPT tutor.
Speak like a close and supportive friend using the right tone for a {profile['age']} {profile['gender']} ({tone} 말투).
The student is learning {profile['target']} and their native language is {profile['native']}.
Correct them gently. Speak naturally and remember previous mistakes.
Give grammar and pronunciation tips. Include voice responses.
Today's topic: weather expressions in {profile['target']}.
{explanation}
"""

# 설문지 흐름
survey_questions = [
    ("company", "🏢 회사명 (Your company name)?"),
    ("teacher", "👩‍🏫 강사 이름 (Your teacher's name)?"),
    ("native", "🗣 모국어가 무엇인가요? (Your native language)?"),
    ("target", "📘 배우고 싶은 언어는 무엇인가요? (Which language would you like to learn?)"),
    ("age", "📅 나이대가 어떻게 되나요? (What is your age group?)"),
    ("gender", "👤 성별이 어떻게 되시나요? (남성/여성)"),
    ("level", "📊 현재 실력은 어느정도인가요? (예: 초급, 중급, 고급 또는 설명으로) (Your level: beginner/intermediate/advanced?)")
]

user_states = {}

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_states[user_id] = 0
    user_profiles[user_id] = {}
    await update.message.reply_text("👋 설문을 시작합니다!\nLet's start the survey!")
    await ask_next_question(update, user_id)

async def ask_next_question(update, user_id):
    state = user_states[user_id]
    if state < len(survey_questions):
        key, question = survey_questions[state]
        await update.message.reply_text(question)
    else:
        await update.message.reply_text("✅ 설문 완료! 수업을 시작합니다.")
        del user_states[user_id]
        await tutor_response("오늘 날씨 어때요?", update, user_profiles[user_id])

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text.strip()

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
            await update.message.reply_text("/start로 설문을 먼저 시작해주세요!")

async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in user_profiles:
        await update.message.reply_text("먼저 /start로 설문을 시작해주세요.")
        return

    file = await context.bot.get_file(update.message.voice.file_id)
    ogg_path = "voice.ogg"
    mp3_path = "voice.mp3"
    await file.download_to_drive(ogg_path)
    AudioSegment.from_ogg(ogg_path).export(mp3_path, format="mp3")

    with open(mp3_path, "rb") as f:
        transcript = openai.audio.transcriptions.create(model="whisper-1", file=f)

    user_input = transcript.text
    await tutor_response(user_input, update, user_profiles[user_id])

async def tutor_response(user_input: str, update: Update, profile: dict):
    try:
        system_prompt = get_system_prompt(profile)

        response = openai.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_input}
            ]
        )
        reply = response.choices[0].message.content
        await update.message.reply_text(reply)

        # 음성 생성
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
    app = ApplicationBuilder().token(os.getenv("TELEGRAM_TOKEN")).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_handler(MessageHandler(filters.VOICE, handle_voice))
    print("✅ CC4AI 튜터 작동 중")
    app.run_polling()
