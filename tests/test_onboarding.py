from evateam_bot.core import formatting
from evateam_bot.core.onboarding import handle_person_query
from evateam_bot.core.models import Person


def test_no_query():
    result = handle_person_query("", [])
    assert result.candidates == []


def test_not_found():
    result = handle_person_query("ghost@x.ru", [])
    assert result.candidates == []
    assert "Не нашёл" in result.message.text


def test_single_candidate_shows_confirm():
    person = Person(id="CmfPerson:1", name="Иван Иванов", email="ivan@x.ru")
    result = handle_person_query("ivan@x.ru", [person])
    assert result.candidates == [person]
    action = result.message.buttons[0][0].action
    assert action == f"{formatting.ACTION_CONFIRM_PREFIX}CmfPerson:1"


def test_multiple_candidates_one_button_each():
    people = [
        Person(id="p1", name="Иван Первый", email="ivan1@x.ru"),
        Person(id="p2", name="Иван Второй", email="ivan2@x.ru"),
    ]
    result = handle_person_query("Иван", people)
    # по кнопке-подтверждению на каждого + кнопка отказа
    confirm_actions = [row[0].action for row in result.message.buttons]
    assert f"{formatting.ACTION_CONFIRM_PREFIX}p1" in confirm_actions
    assert f"{formatting.ACTION_CONFIRM_PREFIX}p2" in confirm_actions
    assert formatting.ACTION_REJECT in confirm_actions
