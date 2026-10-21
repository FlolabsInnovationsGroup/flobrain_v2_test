from rooms.models import MessageTranslation


def translated_text(message, language: str) -> str:
    language = (language or "").strip().lower()
    if not language:
        return message.body
    row, _ = MessageTranslation.objects.get_or_create(
        message=message,
        language=language,
        defaults={"text": f"[{language}] {message.body}"},
    )
    return row.text
