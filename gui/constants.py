APP_VERSION = "1.7.0"

# Plain text; lists prefix STATUS_DOT, which takes the status colour (emoji
# render differently on Windows and macOS and clash with the rest of the UI).
STATUS_DOT = "●"
STATUS_LABELS = {
    "pending":   "В очереди",
    "running":   "В процессе",
    "completed": "Завершено",
    "error":     "Ошибка",
}
STATUS_COLORS = {
    "pending":   "#888888",
    "running":   "#ffa726",
    "completed": "#00c853",
    "error":     "#ff5252",
}
