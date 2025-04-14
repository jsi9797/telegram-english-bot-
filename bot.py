import os
import openai
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters
import requests
from pydub import AudioSegment

openai.api_key = os.getenv("OPENAI_API_KEY")

user_profiles = {}
user_states = {}
user_histories = {}

survey_questions = [
    ("name", "👋 이름을 알려주세요! (What’s your name?)"),
    ("native", "🗣 모국어가 무엇인가요? (Your native language)?"),
    ("target", "📘 배우고 싶은 언어는 무엇인가요? (Which language would you like to learn?)"),
    ("age", "📅 나이대가 어떻게 되나요? (예: 20대, 30대, 40대, 50대 이상)"),
    ("gender", "👤 성별이 어떻게 되시나요? (남성/여성)"),
    ("level", "📊 현재 실력은 어느정도인가요? (예: 초급, 중급, 고급 또는 설명으로)")
]

language_explanation = {
    "Korean": "설명은 한국어로 해주세요.",
    "Japanese": "説明は日本語でお願いします。",
    "Spanish": "Explica en español, por favor.",
    "Vietnamese": "Giải thích bằng tiếng Việt giúp tôi.",
    "Chinese": "请用中文解释。",
    "Indonesian": "Tolong jelaskan dalam Bahasa Indonesia."
}

def get_system_prompt(profile):
    explanation = language_explanation.get(profile['native'], "Explain in English.")
    name = profile.get("name", "학습자")
    level = profile.get("level", "").lower()
    lang = profile.get("target", "the target language")
    
    # 모국어 설명 비율
    if "초급" in level:
        explain_detail = f"{explanation} 영어 표현을 알려주되 예시와 함께 천천히 설명해주세요."
    elif "중급" in level:
        explain_detail = f"{explanation} 영어로 대화하되 필요한 경우만 간단히 모국어로 설명해주세요."
    else:
        explain_detail = f"주로 영어로 설명하고, 복잡한 개념은 {explanation} 간단히 보충해주세요."
    
    return f"""
You are a smart GPT-based language tutor named CC4AI 튜터.
The user's name is {name}, native language is {profile['native']}, and wants to learn {lang}.
Age group: {profile['age']}, Gender: {profile['gender']}, Level: {profile['level']}.
Use {name}님 as the learner's title in every reply.
Your job is to correct grammar and pronunciation based on learner input.
Provide short examples, praise often, and ask natural follow-up questions.
Guide the learner to repeat corrected sentences aloud.
If the learner struggles with pronunciation (like R/L or TH sounds), give friendly correction.
Avoid ending the class prematurely. Keep going unless 20 minutes passed.
{explain_detail}
"""

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_states[user_id] = 0
    user_profiles[user_id] = {}
    user_histories[user_id] = []
    await update.message.reply_text("👋 설문을 시작합니다! Let's start the survey!")
    await ask_next_question(update, user_id)

async def ask_next_question(update, user_id):
    state = user_states[user_id]
    if state < len(survey_questions):
        key, question = survey_questions[state]
        await update.message.reply_text(question)
    else:
        await update.message.reply_text(f"✅ 설문 완료! 이제 수업을 시작할게요 {user_profiles[user_id]['name']}님.")
        del user_states[user_id]
        await tutor_response("수업을 시작하자", update, user_profiles[user_id])

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
            await update.message.reply_text("처음 오셨군요! 설문부터 시작할게요 📝")
            user_states[user_id] = 0
            user_profiles[user_id] = {}
            await ask_next_question(update, user_id)

async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    if user_id not in user_profiles or user_id in user_states:
        await update.message.reply_text("설문을 먼저 완료해주세요 📝")
        return

    file = await context.bot.get_file(update.message.voice.file_id)
    ogg_path = "voice.ogg"
    mp3_path = "voice.mp3"
    await file.download_to_drive(ogg_path)
    AudioSegment.from_ogg(ogg_path).export(mp3_path, format="mp3")

    with open(mp3_path, "rb") as f:
        transcript = openai.audio.transcriptions.create(model="whisper-1", file=f)

    await tutor_response(transcript.text, update, user_profiles[user_id])

async def tutor_response(user_input: str, update: Update, profile: dict):
    try:
        system_prompt = get_system_prompt(profile)
        name = profile.get("name", "회원")

        response = openai.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_input}
            ]
        )
        reply = response.choices[0].message.content
        await update.message.reply_text(reply)

        speech = openai.audio.speech.create(
            model="tts-1",
            voice="nova",
            input=reply
        )
        tts_path = "response.mp3"
        with open(tts_path, "wb") as f:
            f.write(speech.content)

        await update.message.reply_voice(voice=open(tts_path, "rb"))

        # 히스토리 저장
        user_id = update.effective_user.id
        if user_id in user_histories:
            user_histories[user_id].append({"input": user_input, "reply": reply})

    except Exception as e:
        await update.message.reply_text(f"❌ 오류 발생: {str(e)}")

if __name__ == "__main__":
    app = ApplicationBuilder().token(os.getenv("TELEGRAM_TOKEN")).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_handler(MessageHandler(filters.VOICE, handle_voice))
    print("✅ CC4AI 튜터 작동 중")
    app.run_polling()
