# Backlink Checker 1.2.2

Бесплатная программа для Windows и macOS: проверяет сайты-доноры на наличие ссылок на ваши сайты и разбирает качество этих ссылок.

Страницы открываются в реальном Chromium, поэтому видны и ссылки, которые появляются после JavaScript.

Сайт: [artemakulov.ru/backlink-checker](https://artemakulov.ru/backlink-checker/)  
Telegram: [t.me/akulov_pro](https://t.me/akulov_pro)  
Скачать для Windows x64: [BacklinkChecker.exe](https://artemakulov.ru/BacklinkChecker.exe)  
Скачать для macOS (Apple Silicon): [BacklinkChecker-1.2.2-macos-arm64.dmg](https://github.com/AkulovArtem/Backlink-Checker/releases/download/v1.2.2/BacklinkChecker-1.2.2-macos-arm64.dmg)

## Для кого

- SEO-специалисты: массовая проверка ссылочного профиля после размещения ссылок
- владельцы сайтов: контроль купленных ссылок
- линкбилдеры: аудит новых и существующих доноров
- SEO-аналитики: структурированные данные о бэклинках с экспортом в Excel

## Что умеет

- Полный рендеринг JS через headless Chromium
- Прокрутка страницы, чтобы подгрузить lazy-load контент; на бесконечной пагинации останавливается сама
- Поиск ссылок на указанные целевые домены, включая поддомены
- До 100 000 доноров и 50 целевых доменов в одном задании
- Несколько потоков, светлая и тёмная тема, SQLite рядом с exe

### Анализ ссылок

- `rel`: dofollow, nofollow, ugc, sponsored
- тип анкора: текст или картинка (`img` + `alt`)
- текст анкора: из ссылки, `alt` или `title`
- HTML-контекст: ±200 символов вокруг ссылки
- canonical URL

### Индексируемость

Для каждой страницы отдельно для Google, Yandex, Bing и Baidu:

- мета-теги `robots` / `googlebot` / `yandexbot` и т.д.
- HTTP-заголовок `X-Robots-Tag`
- в отчёте: «Открыто» или «Закрыто»

### Технические данные

HTTP-статус, title, число внутренних и внешних ссылок, коды ошибок при недоступности.

## Как пользоваться

1. Запустите `Backlink Checker.exe` от имени администратора. При первом запуске рядом с exe появится база данных.
2. На главном экране нажмите «+ Создать задание» и заполните поля.
3. Проверка идёт в несколько потоков. Клик по заданию открывает отчёт в реальном времени.
4. Результаты можно смотреть в программе или выгрузить в Excel.

## Статусы и ошибки

| Статус | Значение |
|---|---|
| Найдено | страница загружена, ссылка на целевой домен есть |
| Не найдено | страница загружена, ссылки нет |
| Не загружено | страница недоступна, смотрите код ошибки |

| Код | Значение |
|---|---|
| `TIMEOUT` | страница не ответила за отведённое время |
| `NET_ERROR` | сетевая ошибка (DNS, отказ в соединении) |
| `HTTP_4xx` / `HTTP_5xx` | клиентская или серверная HTTP-ошибка |
| `NO_RESPONSE` | браузер не получил ответа |
| `PARSE_ERROR` | ошибка разбора HTML |

## Системные требования

- Windows 10 / 11, 64-bit **или** macOS 12+ на Apple Silicon (M1 и новее)
- от 4 GB RAM (лучше 8+ GB при большом числе потоков)
- установка не нужна: Windows — один exe, macOS — `.app` из DMG
- Chromium внутри программы, отдельно ставить браузер не нужно

На Windows база и лог лежат рядом с exe. На macOS — в `~/Library/Application Support/Backlink Checker/`. Лог: `backlink_checker.log` (ротация 5 МБ × 3 файла).

macOS-сборка не подписана аккаунтом Apple. При первом запуске: правый клик по приложению → Открыть.

## Сборка из исходников

Нужен Python 3.13.

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python -m playwright install chromium
python main.py
```

Windows EXE:

```bat
build.bat
```

macOS DMG (только Apple Silicon):

```bash
./build_macos.sh
```

## Скриншоты

[Интерфейс](https://artemakulov.ru/media/posts/63/gallery/backlink-checker-screenshot.jpg) · [отчёт Excel](https://artemakulov.ru/media/posts/63/gallery/22.jpg)

Больше скриншотов на [странице программы](https://artemakulov.ru/backlink-checker/).
