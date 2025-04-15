async def tutor_response(user_input: str, update: Update, profile: dict, mode: str = None):
    try:
        user_id = update.effective_user.id
        system_prompt = get_system_prompt(profile)
        if not system_prompt or not isinstance(system_prompt, str):
            system_prompt = "You are a helpful tutor. Please guide the learner step-by-step."

        if user_id not in user_histories:
            user_histories[user_id] = []

        if user_id not in user_topics:
            user_topics[user_id] = None

        # 주제를 처음 정했을 경우 저장
        if user_topics[user_id] is None:
            user_topics[user_id] = user_input

        user_histories[user_id].append({"role": "user", "content": user_input})

        # 단어와 문장이 섞이지 않도록 제어
        if 'vocab_phase' not in user_profiles[user_id]:
            user_profiles[user_id]['vocab_phase'] = True

        messages = []
        history = [msg for msg in user_histories[user_id][-10:] if msg.get("content")]
        messages.append({"role": "system", "content": system_prompt})

        if mode == "pronunciation":
            messages.append({
                "role": "user",
                "content": f"The learner said: '{user_input}'. Please carefully analyze the pronunciation word-by-word.\n"
                           "- ✅ Clear if the pronunciation is accurate.\n"
                           "- ⚠️ Needs improvement if the word was unclear, distorted, or incorrect.\n"
                           "Give honest and strict evaluation. If more than 2 words are not clear, ask the learner to try again."
            })
        elif user_profiles[user_id]['vocab_phase']:
            messages.append({
                "role": "user",
                "content": f"Please start an English lesson using the topic '{user_topics[user_id]}'. "
                           f"First, introduce 5 to 10 vocabulary words in {profile['target']} with translations in {profile['native']}. "
                           f"After listing the vocabulary, say: '각 단어를 읽어보시고 준비가 되면 녹음하여 전송 해주세요.' "
                           "Do not include additional instructions or explanations. "
                           "Do not continue to example sentences until the learner finishes the pronunciation step."
            })
        else:
            messages.append({
                "role": "user",
                "content": f"Now continue the lesson by providing 3 to 5 example sentences related to the topic '{user_topics[user_id]}'. "
                           f"For each sentence: 1) Present the English version, 2) Translate it into {profile['native']}, "
                           "and 3) Ask the learner to repeat the sentence aloud. "
                           "Wait for the learner’s response before presenting the next sentence."
            })

        messages += history

        response = openai.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=messages
        )

        reply = response.choices[0].message.content
        user_histories[user_id].append({"role": "assistant", "content": reply})
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

    except Exception as e:
        await update.message.reply_text(f"❌ 오류 발생: {str(e)}")
