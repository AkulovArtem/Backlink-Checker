"""
Export task results to Excel (.xlsx) with 4 sheets.
"""

import json
import logging
from datetime import datetime

import openpyxl
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from db import database as db
from utils.url_utils import matches_target, normalize_domain

logger = logging.getLogger(__name__)

# Colour palette
CLR_HEADER    = "1E1E3A"
CLR_HEADER_FG = "E0E0E0"
CLR_GREEN     = "C8F7DC"
CLR_ORANGE    = "FFE0B2"
CLR_RED       = "FFCDD2"
CLR_ZEBRA     = "F5F5FF"


def _header_font():
    return Font(bold=True, color=CLR_HEADER_FG)


def _header_fill():
    return PatternFill("solid", fgColor=CLR_HEADER)


def _border():
    thin = Side(style="thin", color="CCCCCC")
    return Border(left=thin, right=thin, top=thin, bottom=thin)


def _write_headers(ws, headers: list[str]):
    for col, text in enumerate(headers, 1):
        cell = ws.cell(row=1, column=col, value=text)
        cell.font = _header_font()
        cell.fill = _header_fill()
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        cell.border = _border()
    ws.row_dimensions[1].height = 32


def _auto_width(ws, min_w=10, max_w=60):
    for col in ws.columns:
        max_len = 0
        col_letter = get_column_letter(col[0].column)
        for cell in col:
            try:
                if cell.value:
                    max_len = max(max_len, len(str(cell.value)))
            except Exception:  # nosec B110
                pass
        ws.column_dimensions[col_letter].width = min(max(max_len + 2, min_w), max_w)


def _zebra_fill(row: int) -> PatternFill | None:
    return PatternFill("solid", fgColor=CLR_ZEBRA) if row % 2 == 0 else None


def _http_fill(status_code) -> PatternFill | None:
    if not status_code:
        return None
    grp = status_code // 100
    if grp == 2:
        return PatternFill("solid", fgColor=CLR_GREEN)
    if grp == 4:
        return PatternFill("solid", fgColor=CLR_ORANGE)
    if grp == 5:
        return PatternFill("solid", fgColor=CLR_RED)
    return None


def _write_row(ws, row_idx: int, values: list, zebra: bool = True):
    fill = _zebra_fill(row_idx) if zebra else None
    for col, val in enumerate(values, 1):
        cell = ws.cell(row=row_idx, column=col, value=val)
        cell.alignment = Alignment(vertical="top", wrap_text=True)
        cell.border = _border()
        if fill:
            cell.fill = fill


# ── Sheet builders ─────────────────────────────────────────────────────────

def _sheet_summary(wb, task, target_domains, donors, backlinks):
    ws = wb.create_sheet("Сводка")

    total_donors = len(donors)
    df_count = sum(1 for bl in backlinks if bl["rel_type"] == "dofollow")
    nf_count  = len(backlinks) - df_count
    text_count = sum(1 for bl in backlinks if bl["anchor_type"] == "text")
    img_count  = len(backlinks) - text_count
    open_count   = sum(1 for d in donors if d["index_google"] == "open")
    closed_count = total_donors - open_count

    try:
        dt = datetime.fromisoformat(task["created_at"])
        created_str = dt.strftime("%d.%m.%Y %H:%M")
    except Exception:
        created_str = str(task["created_at"])

    rows = [
        ("Название задания",      task["name"]),
        ("Дата создания",         created_str),
        ("Статус",                task["status"]),
        ("Доноров",               total_donors),
        ("Целевые домены",        ", ".join(target_domains)),
        ("",                      ""),
        ("Всего бэклинков",       len(backlinks)),
        ("Dofollow",              df_count),
        ("Nofollow",              nf_count),
        ("Текстовые анкоры",      text_count),
        ("Графические анкоры",    img_count),
        ("Страниц открыто (Google)", open_count),
        ("Страниц закрыто (Google)", closed_count),
    ]

    ws.column_dimensions["A"].width = 28
    ws.column_dimensions["B"].width = 50

    for r, (key, val) in enumerate(rows, 1):
        ws.cell(row=r, column=1, value=key).font = Font(bold=True)
        ws.cell(row=r, column=2, value=val)


def _sheet_donors(wb, donors, backlinks):
    ws = wb.create_sheet("Доноры")
    headers = [
        "URL донора", "HTTP статус", "Title", "Canonical",
        "Внутр. ссылок", "Внешн. ссылок",
        "Индекс Google", "Индекс Yandex", "Индекс Bing", "Индекс Baidu",
        "Найдено бэклинков"
    ]
    _write_headers(ws, headers)

    bl_counts: dict[int, int] = {}
    for bl in backlinks:
        bl_counts[bl["donor_id"]] = bl_counts.get(bl["donor_id"], 0) + 1

    for row_idx, donor in enumerate(donors, 2):
        http = donor["http_status"]
        values = [
            donor["url"],
            http or donor["error_code"] or "—",
            donor["title"] or "",
            donor["canonical_url"] or "",
            donor["internal_links"] or 0,
            donor["external_links"] or 0,
            donor["index_google"] or "—",
            donor["index_yandex"] or "—",
            donor["index_bing"] or "—",
            donor["index_baidu"] or "—",
            bl_counts.get(donor["id"], 0),
        ]
        _write_row(ws, row_idx, values)
        # Apply HTTP colour to status cell
        status_cell = ws.cell(row=row_idx, column=2)
        http_fill = _http_fill(http)
        if http_fill:
            status_cell.fill = http_fill

    _auto_width(ws)


def _sheet_backlinks(wb, backlinks, donor_map: dict):
    ws = wb.create_sheet("Бэклинки")
    headers = [
        "URL донора", "URL цели", "Анкор",
        "Тип анкора", "Rel", "Контекст (HTML)"
    ]
    _write_headers(ws, headers)

    for row_idx, bl in enumerate(backlinks, 2):
        donor_url = donor_map.get(bl["donor_id"], "")
        _write_row(ws, row_idx, [
            donor_url,
            bl["target_url"],
            bl["anchor_text"] or "",
            bl["anchor_type"] or "",
            bl["rel_type"] or "",
            (bl["context_html"] or "")[:500],
        ])

    _auto_width(ws)


def _sheet_domains(wb, backlinks, target_domains):
    """One row per target domain: found/not-found with backlink and donor counts."""
    ws = wb.create_sheet("По доменам")
    _write_headers(ws, [
        "Целевой домен", "Доноров", "Бэклинков", "Dofollow", "Nofollow", "Статус"
    ])

    for row_idx, orig in enumerate(target_domains, 2):
        norm = normalize_domain(orig)
        matched = [
            bl for bl in backlinks
            if matches_target(bl["target_url"] or "", norm)
        ]
        donors = len({bl["donor_id"] for bl in matched})
        df = sum(1 for bl in matched if bl["rel_type"] == "dofollow")
        nf = len(matched) - df
        found = len(matched) > 0

        _write_row(ws, row_idx, [orig, donors, len(matched), df, nf,
                                  "Найден" if found else "Не найден"])
        ws.cell(row=row_idx, column=6).fill = PatternFill(
            "solid", fgColor=CLR_GREEN if found else CLR_RED
        )

    _auto_width(ws)


def _sheet_anchors(wb, anchor_stats):
    ws = wb.create_sheet("Топ анкоры")
    _write_headers(ws, ["Анкор", "Количество", "% от общего"])

    total = sum(r["cnt"] for r in anchor_stats) or 1
    for row_idx, row in enumerate(anchor_stats, 2):
        pct = f"{row['cnt'] / total * 100:.1f}%"
        _write_row(ws, row_idx, [
            row["anchor_text"] or "(пусто)",
            row["cnt"],
            pct,
        ])

    _auto_width(ws)


# ── Public API ─────────────────────────────────────────────────────────────

def export_to_excel(task_id: int, output_path: str) -> None:
    task = db.get_task(task_id)
    if not task:
        raise ValueError(f"Task {task_id} not found")

    try:
        target_domains = json.loads(task["target_domains"])
    except (json.JSONDecodeError, TypeError) as exc:
        logger.error("Corrupted target_domains for task %d: %s", task_id, exc)
        raise ValueError(f"Task {task_id} has corrupted target_domains") from exc
    donors = db.get_donors_for_task(task_id)
    backlinks = db.get_backlinks_for_task(task_id)
    anchor_stats = db.get_anchor_stats(task_id)

    donor_map = {d["id"]: d["url"] for d in donors}

    wb = openpyxl.Workbook()
    wb.remove(wb.active)  # remove default sheet

    _sheet_summary(wb, task, target_domains, donors, backlinks)
    _sheet_domains(wb, backlinks, target_domains)
    _sheet_donors(wb, donors, backlinks)
    _sheet_backlinks(wb, backlinks, donor_map)
    _sheet_anchors(wb, anchor_stats)

    wb.save(output_path)
    logger.info("Exported task %d → %s", task_id, output_path)
