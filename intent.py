from config import MODEL, INTENT_SYSTEM, INTENT_USER_TEMPLATE, VALID_INTENTS


def classify(user_input: str, client) -> str:
    try:
        response = client.messages.create(
            model=MODEL,
            max_tokens=20,
            system=INTENT_SYSTEM,
            messages=[
                {
                    "role": "user",
                    "content": INTENT_USER_TEMPLATE.format(user_input=user_input),
                }
            ],
        )
        label = response.content[0].text.strip().lower()
        if label in VALID_INTENTS:
            return label
        for valid in VALID_INTENTS:
            if valid in label:
                return valid
    except Exception:
        pass
    return "general_chat"
