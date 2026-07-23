"""Чистая логика онбординга: интерпретация результата поиска пользователя."""

from __future__ import annotations

from dataclasses import dataclass

from . import formatting
from .messages import Button, OutgoingMessage
from .models import Person


@dataclass
class OnboardingResult:
    """Что показать пользователю и каких кандидатов запомнить для подтверждения."""

    message: OutgoingMessage
    candidates: list[Person]


def handle_person_query(query: str, people: list[Person]) -> OnboardingResult:
    query = query.strip()
    if not query:
        return OnboardingResult(formatting.welcome_message(), [])
    if not people:
        return OnboardingResult(formatting.person_not_found_message(query), [])
    if len(people) == 1:
        return OnboardingResult(formatting.confirm_person_message(people[0]), people)
    return OnboardingResult(_choose_message(people), people)


def _choose_message(people: list[Person]) -> OutgoingMessage:
    rows = []
    for person in people:
        ident = person.email or person.login or ""
        label = f"✅ {person.name}" + (f" ({ident})" if ident else "")
        rows.append([Button(text=label, action=f"{formatting.ACTION_CONFIRM_PREFIX}{person.id}")])
    rows.append([Button(text="❌ Никто из них", action=formatting.ACTION_REJECT)])
    return OutgoingMessage(
        text="Нашлось несколько учётных записей. Выберите свою:", buttons=rows
    )
