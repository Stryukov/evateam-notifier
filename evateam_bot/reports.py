"""Запись отчётов на диск — единственное место, где сводка касается файловой системы.

`core/` остаётся без I/O: рендеры возвращают строки, а раскладывает их по файлам
этот модуль. Возвращает и путь, и байты — транспорту не нужно перечитывать файл.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, is_dataclass
from datetime import date, datetime
from enum import Enum
from pathlib import Path
from typing import Any

from .core.models import Summary
from .core.summary_csv import render_timeline_csv
from .core.summary_html import render_html

FILENAME_PREFIX = "evateam-summary"


@dataclass(frozen=True)
class ReportArtifact:
    filename: str
    content: bytes
    mime_type: str
    path: Path


@dataclass(frozen=True)
class ReportFiles:
    html: ReportArtifact
    csv: ReportArtifact
    json: ReportArtifact

    @property
    def all(self) -> list[ReportArtifact]:
        return [self.html, self.csv, self.json]


def write_report_files(
    summary: Summary, *, output_dir: str, now: datetime | None = None
) -> ReportFiles:
    now = now or summary.generated_at
    directory = Path(output_dir)
    os.makedirs(directory, exist_ok=True)
    stem = f"{FILENAME_PREFIX}-{now.strftime('%Y%m%d-%H%M')}"

    return ReportFiles(
        html=_write(
            directory, f"{stem}.html", render_html(summary).encode("utf-8"), "text/html"
        ),
        # utf-8-sig: без BOM Excel открывает кириллицу кракозябрами.
        csv=_write(
            directory,
            f"{stem}.csv",
            render_timeline_csv(summary).encode("utf-8-sig"),
            "text/csv",
        ),
        # Машиночитаемый снимок: задел под раздел «изменения с прошлого отчёта».
        json=_write(
            directory,
            f"{stem}.json",
            json.dumps(asdict(summary), ensure_ascii=False, indent=2, default=_encode).encode(
                "utf-8"
            ),
            "application/json",
        ),
    )


def _write(directory: Path, filename: str, content: bytes, mime_type: str) -> ReportArtifact:
    path = directory / filename
    path.write_bytes(content)
    return ReportArtifact(filename=filename, content=content, mime_type=mime_type, path=path)


def _encode(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if is_dataclass(value):
        return asdict(value)
    return str(value)
