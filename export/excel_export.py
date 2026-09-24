"""
Export task results to Excel (.xlsx) with 5 sheets.
"""

import json
import logging
import re
from collections import defaultdict
from datetime import datetime, timezone

import openpyxl
from openpyxl.styles import Alignment, Border, Font, NamedStyle, PatternFill, Side
from openpyxl.utils import get_column_letter

from db import database as db
from utils.url_utils import get_domain, matches_target, normalize_domain, same_page

logger = logging.getLogger(__name__)

# XML 1.0 prohibits control characters except \t \n \r; also surrogates and U+FFFE/FFFF.
# Scraped content can contain them, causing Excel's "recovery" dialog on open.
_ILLEGAL_XML_RE = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f￾￿]")


def _sanitize(val):
    """Strip illegal XML 1.0 characters from strings so Excel opens without errors."""
    if isinstance(val, str):
        return _ILLEGAL_XML_RE.sub("", val)
    return val


# Colour palette — 8-char ARGB (AARRGGBB) as required by OOXML spec.
# 6-char RGB causes Excel to show a "recovery" dialog on open.
CLR_HEADER    = "FF1E1E3A"
CLR_HEADER_FG = "FFE0E0E0"
CLR_GREEN     = "FFC8F7DC"
CLR_ORANGE    = "FFFFE0B2"
CLR_RED       = "FFFFCDD2"
CLR_ZEBRA     = "FFF5F5FF"
CLR_WHITE     = "FFFFFFFF"
CLR_BORDER    = "FFCCCCCC"


# Named styles, registered once per workbook. Assigning a fresh Font/Border/
# Fill per cell made openpyxl hash and dedupe style objects for every cell —
# ~5 minutes for a 100k-donor task. A named style is a single lookup.
STYLE_HEADER = "bc_header"
STYLE_BODY = "bc_body"
STYLE_ZEBRA = "bc_zebra"
_STYLE_BY_FILL = {CLR_GREEN: "bc_green", CLR_ORANGE: "bc_orange", CLR_RED: "bc_red"}

_WIDTH_SAMPLE_ROWS = 2000


def _solid(color: str) -> PatternFill:
    return PatternFill(patternType="solid", fgColor=color, bgColor=CLR_WHITE)


def _register_styles(wb) -> None:
    thin = Side(style="thin", color=CLR_BORDER)
    border = Border(left=thin, right=thin, top=thin, bottom=thin)
    body_align = Alignment(vertical="top", wrap_text=True)
    wb.add_named_style(NamedStyle(
        name=STYLE_HEADER,
        font=Font(bold=True, color=CLR_HEADER_FG),
        fill=_solid(CLR_HEADER),
        alignment=Alignment(horizontal="center", vertical="center", wrap_text=True),
        border=border,
    ))
    wb.add_named_style(NamedStyle(name=STYLE_BODY, alignment=body_align, border=border))
    wb.add_named_style(NamedStyle(
        name=STYLE_ZEBRA, alignment=body_align, border=border, fill=_solid(CLR_ZEBRA)
    ))
    for color, name in _STYLE_BY_FILL.items():
        wb.add_named_style(NamedStyle(
            name=name, alignment=body_align, border=border, fill=_solid(color)
        ))


def _write_headers(ws, headers: list[str]):
    for col, text in enumerate(headers, 1):
        ws.cell(row=1, column=col, value=text).style = STYLE_HEADER
    ws.row_dimensions[1].height = 32


def _auto_width(ws, min_w=10, max_w=60):
    """Fit columns to content, judged by the first rows (like Qt's resize-to-contents)."""
    widths: dict[int, int] = {}
    for row in ws.iter_rows(max_row=min(ws.max_row, _WIDTH_SAMPLE_ROWS)):
        for cell in row:
            if cell.value is not None and cell.value != "":
                widths[cell.column] = max(widths.get(cell.column, 0), len(str(cell.value)))
    for col in range(1, ws.max_column + 1):
        width = widths.get(col, 0) + 2
        ws.column_dimensions[get_column_letter(col)].width = min(max(width, min_w), max_w)


def _finish_table(ws) -> None:
    """Column widths, a header that stays visible while scrolling, and filters."""
    _auto_width(ws)
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions


def _http_fill(status_code) -> str | None:
    """Fill colour for an HTTP status cell, or None."""
    if not status_code:
        return None
    return {2: CLR_GREEN, 4: CLR_ORANGE, 5: CLR_RED}.get(status_code // 100)


def _paint(cell, color: str | None) -> None:
    if color is not None:
        cell.style = _STYLE_BY_FILL[color]


def _write_row(ws, row_idx: int, values: list, zebra: bool = True):
    style = STYLE_ZEBRA if zebra and row_idx % 2 == 0 else STYLE_BODY
    for col, val in enumerate(values, 1):
        sanitized = _sanitize(val)
        cell = ws.cell(row=row_idx, column=col)
        cell.value = sanitized
        if isinstance(sanitized, str):
            # openpyxl auto-sets data_type='f' for strings starting with '=';
            # override to 's' so scraped content is never treated as a formula.
            cell.data_type = "s"
        cell.style = style


# ── Sheet builders ─────────────────────────────────────────────────────────

_ROBOTS_RU = {"open": "Открыто", "closed": "Закрыто"}
_GINDEX_RU = {"indexed": "Да", "not_indexed": "Нет", "error": "Ошибка"}


_DONOR_STATUS_RU = {
    "found": "Найдено",
    "not_found": "Не найдено",
    "not_loaded": "Не загружено",
    "pending": "В очереди",
}
# Same colours as the in-app report: found green, not found orange, error red.
_STATUS_FILL = {"found": CLR_GREEN, "not_found": CLR_ORANGE, "not_loaded": CLR_RED}
_VALUE_FILL_COLUMNS = (
    "Robots Google", "Robots Yandex", "Robots Bing", "Robots Baidu",
    "В индексе Google", "Ошибка индекса Google",
)


def _row_value(row, key: str):
    try:
        return row[key]
    except (KeyError, IndexError):
        return None


def _donor_gindex(donor) -> str:
    try:
        return donor["google_indexed"] or ""
    except (KeyError, IndexError):
        return ""


def _donor_gindex_error(donor) -> str:
    try:
        return donor["google_index_error"] or ""
    except (KeyError, IndexError):
        return ""


def _donor_html_snippet(donor) -> str:
    try:
        return donor["html_snippet"] or ""
    except (KeyError, IndexError):
        return ""


def _donor_submitted_at(donor) -> str:
    try:
        return donor["index_submitted_at"] or ""
    except (KeyError, IndexError):
        return ""


def _task_send_label(task) -> str:
    try:
        if not task["send_to_index"]:
            return "Нет"
    except (KeyError, IndexError):
        return "Нет"
    try:
        name = str(task["index_submitter"] or "").strip()
    except (KeyError, IndexError):
        name = ""
    if name == "speedyindex":
        return "SpeedyIndex"
    return name or "Да"


def _format_submitted_at(raw: str) -> str:
    if not raw:
        return "—"
    text = str(raw).strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return "—"
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone().strftime("%d.%m.%Y %H:%M")


def _robots_label(value) -> str:
    if not value:
        return "—"
    return _ROBOTS_RU.get(value, str(value))


def _gindex_label(value) -> str:
    if not value:
        return "—"
    return _GINDEX_RU.get(value, "—")


def _value_fill(value) -> str | None:
    """Fill colour for a Robots / В индексе Google cell, or None."""
    if value in ("Открыто", "Да"):
        return CLR_GREEN
    if value in ("Закрыто", "Нет"):
        return CLR_RED
    if value == "Ошибка":
        return CLR_ORANGE
    return None


def _sheet_summary(wb, task, target_domains, donors, backlinks):
    ws = wb.create_sheet("Сводка")

    total_donors = len(donors)
    df_count = sum(1 for bl in backlinks if bl["rel_type"] == "dofollow")
    nf_count  = len(backlinks) - df_count
    text_count = sum(1 for bl in backlinks if bl["anchor_type"] == "text")
    img_count  = len(backlinks) - text_count
    open_count   = sum(1 for d in donors if d["index_google"] == "open")
    closed_count = sum(1 for d in donors if d["index_google"] == "closed")
    unknown_count = total_donors - open_count - closed_count  # not loaded / pending
    g_yes = sum(1 for d in donors if _donor_gindex(d) == "indexed")
    g_no = sum(1 for d in donors if _donor_gindex(d) == "not_indexed")
    g_err = sum(1 for d in donors if _donor_gindex(d) == "error")
    g_skip = total_donors - g_yes - g_no - g_err

    _STATUS_RU = {
        "pending":   "В очереди",
        "running":   "В процессе",
        "completed": "Завершено",
        "error":     "Ошибка",
    }

    created_str = db.format_task_created(task["created_at"])

    rows = [
        ("Название задания",         task["name"]),
        ("Дата создания",            created_str),
        ("Статус",                   _STATUS_RU.get(task["status"], task["status"])),
        ("Доноров",                  total_donors),
        ("Целевые домены",           ", ".join(target_domains)),
        ("",                         ""),
        ("Всего бэклинков",          len(backlinks)),
        ("Dofollow",                 df_count),
        ("Nofollow",                 nf_count),
        ("Текстовые анкоры",         text_count),
        ("Графические анкоры",       img_count),
        ("Robots открыто (Google)",  open_count),
        ("Robots закрыто (Google)",  closed_count),
        ("Robots не определено",     unknown_count),
        ("В индексе Google (да)",    g_yes),
        ("В индексе Google (нет)",   g_no),
        ("В индексе Google (ошибка)", g_err),
        ("В индексе Google (не проверялось)", g_skip),
        ("Отправка на индексацию",   _task_send_label(task)),
        ("Доноров отправлено на индексацию",
         sum(1 for d in donors if _donor_submitted_at(d))),
    ]

    ws.column_dimensions["A"].width = 36
    ws.column_dimensions["B"].width = 50

    for r, (key, val) in enumerate(rows, 1):
        ws.cell(row=r, column=1, value=key).font = Font(bold=True)
        sanitized = _sanitize(val)
        cell2 = ws.cell(row=r, column=2)
        cell2.value = sanitized
        if isinstance(sanitized, str):
            cell2.data_type = "s"


def _sheet_donors(wb, donors, backlinks):
    ws = wb.create_sheet("Доноры")
    headers = [
        "URL донора", "Статус", "HTTP статус", "Итоговый URL",
        "Title", "Canonical", "HTML сниппет",
        "Внутр. ссылок", "Внешн. ссылок",
        "Robots Google", "Robots Yandex", "Robots Bing", "Robots Baidu",
        "В индексе Google", "Ошибка индекса Google",
        "Отправлено на индексацию", "Дата отправки на индексацию",
        "Найдено бэклинков"
    ]
    _write_headers(ws, headers)
    col = {name: i for i, name in enumerate(headers, 1)}

    bl_counts: dict[int, int] = {}
    for bl in backlinks:
        bl_counts[bl["donor_id"]] = bl_counts.get(bl["donor_id"], 0) + 1

    for row_idx, donor in enumerate(donors, 2):
        http = donor["http_status"]
        final_url = _row_value(donor, "final_url") or ""
        values = [
            donor["url"],
            _DONOR_STATUS_RU.get(donor["status"], donor["status"] or "—"),
            http or donor["error_code"] or "—",
            # Only a real redirect is worth a value — not Chromium's "/" or %-encoding.
            final_url if final_url and not same_page(final_url, donor["url"]) else "",
            donor["title"] or "",
            donor["canonical_url"] or "",
            _donor_html_snippet(donor),
            donor["internal_links"] or 0,
            donor["external_links"] or 0,
            _robots_label(donor["index_google"]),
            _robots_label(donor["index_yandex"]),
            _robots_label(donor["index_bing"]),
            _robots_label(donor["index_baidu"]),
            _gindex_label(_donor_gindex(donor)),
            _donor_gindex_error(donor),
            "Да" if _donor_submitted_at(donor) else "Нет",
            _format_submitted_at(_donor_submitted_at(donor)),
            bl_counts.get(donor["id"], 0),
        ]
        _write_row(ws, row_idx, values)
        _paint(ws.cell(row=row_idx, column=col["Статус"]), _STATUS_FILL.get(donor["status"]))
        _paint(ws.cell(row=row_idx, column=col["HTTP статус"]), _http_fill(http))
        for name in _VALUE_FILL_COLUMNS:
            cell = ws.cell(row=row_idx, column=col[name])
            _paint(cell, _value_fill(cell.value))

    _finish_table(ws)


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

    _finish_table(ws)


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
        _paint(ws.cell(row=row_idx, column=6), CLR_GREEN if found else CLR_RED)

    _finish_table(ws)


def _sheet_anchors(wb, anchor_stats):
    ws = wb.create_sheet("Топ анкоры")
    _write_headers(ws, ["Анкор", "Ссылки", "Домены", "Dofollow", "Nofollow", "% от общего"])

    # Numbers stay numbers so Excel can sort, filter and sum them.
    for row_idx, row in enumerate(anchor_stats, 2):
        _write_row(ws, row_idx, [
            row["anchor_text"] or "(пусто)",
            row["cnt"],
            row["domains"],
            row["dofollow"],
            row["nofollow"],
            row["pct"] / 100,
        ])
        ws.cell(row=row_idx, column=6).number_format = "0.0%"

    _finish_table(ws)


# ── Public API ─────────────────────────────────────────────────────────────

_FILENAME_FORBIDDEN_RE = re.compile(r'[\\/:*?"<>|\x00-\x1f]+')
_FILENAME_MAX = 100
# Device names Windows refuses as file names, even with an extension.
_WINDOWS_RESERVED = frozenset(
    {"CON", "PRN", "AUX", "NUL"}
    | {f"COM{i}" for i in range(1, 10)}
    | {f"LPT{i}" for i in range(1, 10)}
)


def export_filename(task_name: str, task_id: int) -> str:
    """Default .xlsx name: the task name made safe for Windows and macOS."""
    name = _FILENAME_FORBIDDEN_RE.sub("_", task_name or "")
    name = " ".join(name.split())[:_FILENAME_MAX].strip(" .")
    if name.upper() in _WINDOWS_RESERVED:
        name += "_"
    return f"{name or f'task_{task_id}'}.xlsx"


def export_to_excel(task_id: int, output_path: str) -> None:
    task = db.get_task(task_id)
    if not task:
        raise ValueError(f"Task {task_id} not found")

    try:
        target_domains = db.parse_target_domains(task["target_domains"])
    except (json.JSONDecodeError, TypeError) as exc:
        logger.error("Corrupted target_domains for task %d: %s", task_id, exc)
        raise ValueError(f"Task {task_id} has corrupted target_domains") from exc
    donors = db.get_donors_for_task(task_id)
    backlinks = db.get_backlinks_for_task(task_id)

    donor_map = {d["id"]: d["url"] for d in donors}

    # Rich anchor stats — same logic as report_view for consistency
    _anchor_groups: dict[str, list] = defaultdict(list)
    for _bl in backlinks:
        _anchor_groups[_bl["anchor_text"] or ""].append(_bl)
    _total_bl = len(backlinks)
    anchor_stats = []
    for _anchor, _bls in sorted(_anchor_groups.items(), key=lambda x: -len(x[1])):
        _df = sum(1 for b in _bls if b["rel_type"] == "dofollow")
        _domains = len({
            get_domain(donor_map.get(b["donor_id"], ""))
            for b in _bls
            if donor_map.get(b["donor_id"])
        })
        anchor_stats.append({
            "anchor_text": _anchor,
            "cnt":         len(_bls),
            "domains":     _domains,
            "dofollow":    _df,
            "nofollow":    len(_bls) - _df,
            "pct":         len(_bls) / _total_bl * 100 if _total_bl > 0 else 0.0,
        })

    wb = openpyxl.Workbook()
    wb.remove(wb.active)  # remove default sheet
    _register_styles(wb)

    _sheet_summary(wb, task, target_domains, donors, backlinks)
    _sheet_domains(wb, backlinks, target_domains)
    _sheet_donors(wb, donors, backlinks)
    _sheet_backlinks(wb, backlinks, donor_map)
    _sheet_anchors(wb, anchor_stats)

    wb.save(output_path)
    logger.info("Exported task %d → %s", task_id, output_path)
