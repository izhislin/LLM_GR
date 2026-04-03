"""Вычисление conversation metrics из transcript_segments.

Метрики извлекаются из таймкодов сегментов (чистая арифметика, без LLM).
"""

from __future__ import annotations

SILENCE_THRESHOLD_SEC = 2.0
OPERATOR_SPEAKERS = {"Оператор", "operator"}


def compute_metrics(segments: list[dict]) -> dict:
    """Вычислить метрики разговора из списка сегментов.

    Args:
        segments: список dict с ключами speaker, text, start, end.

    Returns:
        dict с метриками (operator_talk_sec, client_talk_sec, silence_sec,
        longest_silence_sec, interruptions_count, operator_talk_ratio,
        avg_operator_turn_sec, avg_client_turn_sec, total_turns).
    """
    if not segments:
        return {
            "operator_talk_sec": 0.0,
            "client_talk_sec": 0.0,
            "silence_sec": 0.0,
            "longest_silence_sec": 0.0,
            "interruptions_count": 0,
            "operator_talk_ratio": 0.0,
            "avg_operator_turn_sec": 0.0,
            "avg_client_turn_sec": 0.0,
            "total_turns": 0,
        }

    operator_talk = 0.0
    client_talk = 0.0
    operator_turns = 0
    client_turns = 0

    for seg in segments:
        duration = max(0.0, seg["end"] - seg["start"])
        if seg["speaker"] in OPERATOR_SPEAKERS:
            operator_talk += duration
            operator_turns += 1
        else:
            client_talk += duration
            client_turns += 1

    # Silence: gaps > SILENCE_THRESHOLD between consecutive segments
    sorted_segs = sorted(segments, key=lambda s: s["start"])
    silence_sec = 0.0
    longest_silence = 0.0
    for i in range(1, len(sorted_segs)):
        gap = sorted_segs[i]["start"] - sorted_segs[i - 1]["end"]
        if gap > SILENCE_THRESHOLD_SEC:
            silence_sec += gap
            longest_silence = max(longest_silence, gap)

    # Interruptions: overlapping segments from different speakers
    interruptions = 0
    for i in range(1, len(sorted_segs)):
        prev = sorted_segs[i - 1]
        curr = sorted_segs[i]
        if curr["start"] < prev["end"] and curr["speaker"] != prev["speaker"]:
            interruptions += 1

    total_talk = operator_talk + client_talk
    total_turns = operator_turns + client_turns

    return {
        "operator_talk_sec": round(operator_talk, 2),
        "client_talk_sec": round(client_talk, 2),
        "silence_sec": round(silence_sec, 2),
        "longest_silence_sec": round(longest_silence, 2),
        "interruptions_count": interruptions,
        "operator_talk_ratio": round(operator_talk / total_talk, 3) if total_talk > 0 else 0.0,
        "avg_operator_turn_sec": round(operator_talk / operator_turns, 2) if operator_turns > 0 else 0.0,
        "avg_client_turn_sec": round(client_talk / client_turns, 2) if client_turns > 0 else 0.0,
        "total_turns": total_turns,
    }
