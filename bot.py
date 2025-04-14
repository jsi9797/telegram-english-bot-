import os
import openai
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters
from pydub import AudioSegment
import json
from datetime import datetime

openai.api_key = os.getenv("OPENAI_API_KEY")

HISTORY_FOLDER = "history"
os.makedirs(HISTORY_FOLDER, exist_ok=True)

def get_history_path(user_id):
    return os.path.join(HISTORY_FOLDER, f"{user_id}.json")

def load_history(user_id):
    path = get_history_path(user_id)
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"profile": {}, "history": []}

def save_history(user_id, profile, history):
    path = get_history_path(user_id)
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"profile": profile, "history": history}, f, ensure_ascii=False, indent=2)

language_explanation = {
    "Korean": "설명은 한국어로 해주세요.",
    "Japanese": "説明は日本語でお願いします。",
    "Spanish": "Explica en español, por favor.",
    "Vietnamese": "Giải thích bằng tiếng Việt giúp tôi.",
    "Chinese": "请用中文解释。",
    "Indonesian": "Tolong jelaskan dalam Bahasa Indonesia.",
}

def get_system_prompt(profile):
    native = profile.get("native", "Korean")
    target = profile.get("target", "English")
    level = profile.get("level", "초급")
    explanation = language_explanation.get(native, "Explain in English.")
    name = profile.get("name", "형님")

    if level == "초급":
        lang_ratio = "80% 모국어 설명, 20% 학습 언어"
    elif level == "중급":
        lang_ratio = "50% 모국어 설명, 50% 학습 언어"
    else:
        lang_ratio = "거의 학습 언어로만 설명"

    return f"""
너는 CC4AI 튜터야. 학습자 이름은 {name}이고, 모국어는 {native}, 배우고 싶은 언어는 {target}, 현재 레벨은 {level}이야.
설명은 {explanation}로 해줘. 설명 비율은 {lang_ratio}야.
학습자가 먼저 말하면, 그 내용에 대해 문법, 발음, 단어 등 학습 포인트를 자연스럽게 뽑아줘.
가능하면 예시 문장도 주고, 따라 말하게 하고, 음성으로도 전달해.
이전에 학습자가 한 말과 실수를 기억하고 연결해서 알려줘.
절대로 혼자서 수업 끝내지 말고, 학습자가 끝낼 때까지 흐름을 이어가.
"""

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    first_name = update.effective_user.first_name
    history_data = load_history(user_id)
    history_data["profile"]["name"] = first_name + "님"
    save_history(user_id, history_data["profile"], history_data["history"])
    await update.message.reply_text(f"{first_name}님, 안녕하세요! 수업을 시작할게요. 오늘은 취미에 대해 이야기해볼까요? 어떤 취미를 가지고 계신가요?")

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_input = update.message.text.strip()
    history_data = load_history(user_id)
    profile = history_data.get("profile", {})
    history = history_data.get("history", [])

    history.append({"user": user_input, "time": str(datetime.now())})
    save_history(user_id, profile, history)

    system_prompt = get_system_prompt(profile)

    response = openai.chat.completions.create(
        model="gpt-3.5-turbo",
        messages=[
            {"role": "system", "content": system_prompt},
            *[
                {"role": "user", "content": item["user"]}
                for item in history[-5:]
            ],
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

async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    file = await context.bot.get_file(update.message.voice.file_id)
    ogg_path = "voice.ogg"
    mp3_path = "voice.mp3"
    await file.download_to_drive(ogg_path)
    AudioSegment.from_ogg(ogg_path).export(mp3_path, format="mp3")

    with open(mp3_path, "rb") as f:
        transcript = openai.audio.transcriptions.create(model="whisper-1", file=f)

    update.message.text = transcript.text
    await handle_text(update, context)

if __name__ == "__main__":
    app = ApplicationBuilder().token(os.getenv("TELEGRAM_TOKEN")).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_handler(MessageHandler(filters.VOICE, handle_voice))
    print("✅ CC4AI 튜터 작동 중")
    app.run_polling()
