"""Сборка хронологического диалога из двух каналов."""

from dataclasses import dataclass

from src.transcriber import Utterance


@dataclass
class DialogueTurn:
    """Одна реплика в диалоге."""
    speaker: str
    text: str
    start: float
    end: float

    def __str__(self) -> str:
        timestamp = _format_timestamp(self.start)
        return f"[{timestamp}] {self.speaker}: {self.text}"


def _format_timestamp(seconds: float) -> str:
    """Форматировать секунды в HH:MM:SS."""
    total = int(seconds)
    h = total // 3600
    m = (total % 3600) // 60
    s = total % 60
    return f"{h:02d}:{m:02d}:{s:02d}"


def build_dialogue(
    operator_utterances: list[Utterance],
    client_utterances: list[Utterance],
) -> list[DialogueTurn]:
    """Собрать хронологический диалог из двух каналов.

    Фразы из обоих каналов объединяются и сортируются по времени начала.

    Args:
        operator_utterances: Фразы оператора (левый канал).
        client_utterances: Фразы клиента (правый канал).

    Returns:
        Список DialogueTurn, отсортированный хронологически.
    """
    turns: list[DialogueTurn] = []

    for utt in operator_utterances:
        turns.append(DialogueTurn(
            speaker="Оператор", text=utt.text, start=utt.start, end=utt.end,
        ))

    for utt in client_utterances:
        turns.append(DialogueTurn(
            speaker="Клиент", text=utt.text, start=utt.start, end=utt.end,
        ))

    turns.sort(key=lambda t: t.start)
    return turns


def dialogue_to_text(dialogue: list[DialogueTurn]) -> str:
    """Преобразовать диалог в читаемый текст."""
    return "\n".join(str(turn) for turn in dialogue)
