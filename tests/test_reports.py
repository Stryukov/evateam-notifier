import json
from datetime import datetime

from evateam_bot.core.models import Epic, Portfolio, StatusCategory
from evateam_bot.core.summary import build_summary
from evateam_bot.reports import write_report_files

NOW = datetime(2026, 8, 5, 13, 40)


def _summary():
    epic = Epic(
        id="e1",
        code="BLT-1",
        title="Эпик «Биллинг»",
        status_code="in_progress",
        status_name="В работе",
        status_category=StatusCategory.IN_PROGRESS,
        project_id="p1",
        project_name="Проект",
        plan_start=datetime(2026, 8, 1),
        plan_end=datetime(2026, 9, 1),
    )
    return build_summary(Portfolio(epics=[epic], project_names={"p1": "Проект"}), now=NOW)


def test_writes_three_files_with_timestamped_names(tmp_path):
    files = write_report_files(_summary(), output_dir=str(tmp_path))

    assert files.html.path.exists() and files.csv.path.exists() and files.json.path.exists()
    for artifact in files.all:
        assert "20260805-1340" in artifact.filename
        assert artifact.path.read_bytes() == artifact.content


def test_creates_missing_directory(tmp_path):
    target = tmp_path / "nested" / "reports"
    files = write_report_files(_summary(), output_dir=str(target))
    assert files.html.path.parent == target


def test_html_is_utf8_and_readable(tmp_path):
    files = write_report_files(_summary(), output_dir=str(tmp_path))
    text = files.html.path.read_text(encoding="utf-8")
    assert "Эпик «Биллинг»" in text
    assert files.html.mime_type == "text/html"


def test_csv_has_bom_for_excel(tmp_path):
    """Без BOM Excel открывает кириллицу кракозябрами."""
    files = write_report_files(_summary(), output_dir=str(tmp_path))
    assert files.csv.content.startswith(b"\xef\xbb\xbf")
    assert files.csv.path.read_text(encoding="utf-8-sig").startswith("Card title")


def test_json_snapshot_is_machine_readable(tmp_path):
    files = write_report_files(_summary(), output_dir=str(tmp_path))
    payload = json.loads(files.json.path.read_text(encoding="utf-8"))

    assert payload["generated_at"] == NOW.isoformat()
    assert payload["projects"][0]["name"] == "Проект"
    # Enum сериализуется значением, а не repr.
    assert payload["projects"][0]["epics"][0]["health"] in {"late", "risk", "ok", "no_date"}


def test_explicit_now_overrides_summary_timestamp(tmp_path):
    files = write_report_files(
        _summary(), output_dir=str(tmp_path), now=datetime(2027, 1, 2, 3, 4)
    )
    assert "20270102-0304" in files.html.filename
