
#!/usr/bin/env python3
"""Сборка all.m3u из sources.txt с сохранением настроек воспроизведения."""

import os
import re
import sys
import time
import urllib.request

SOURCES_FILE = "sources.txt"
OUTPUT_FILE = "all.m3u"
MIN_ENTRIES = 300

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

BAD_URL = re.compile(
    r"^(rtsp:|rtmp:)|youtube\.com|youtu\.be|twitch\.tv|dailymotion\.com",
    re.I,
)

GROUP_RULES = [
    ("DROP", r"shop|магазин|торговл"),
    ("18+", r"xxx|adult|18\+|взросл|erotic|эротик"),
    ("Новости", r"news|новост|информац|ньюс|business|бизнес|economy|финанс"),
    ("Спорт", r"sport|спорт"),
    ("Музыка", r"music|музык|radio|радио"),
    ("Детские", r"kids|child|cartoon|animation|мульт|детск"),
    ("Религия", r"relig|христиан|правосл|ислам"),
    ("Региональные", r"local|region|местн|област|регион"),
    ("Кино и сериалы", r"movie|film|cinema|кино|фильм|сериал|series|comed|комед|драм|drama|thriller|horror|триллер|ужас|боевик|мелодрам"),
    ("Познавательные", r"document|educat|science|познават|образоват|наук|хобби|lifestyle|outdoor|travel|cooking|nature|culture|культур|histor|истори|weather|auto|авто"),
    ("Федеральные", r"general|entertainment|развлек|общественн|эфир|public|federal|федеральн|interactive"),
]

GROUP_ORDER = [
    "Федеральные", "Новости", "Кино и сериалы", "Спорт",
    "Музыка", "Детские", "Познавательные",
    "Региональные", "Религия", "18+", "Разное"
]

NAME_DROP = re.compile(
    r"teleshop|телемагазин|shopping|\bqvc\b|\bhsn\b", re.I
)

GROUP_RE = re.compile(r'group-title="([^"]*)"', re.I)

# Признаки русскоязычного канала.
RU_ID = re.compile(r'tvg-id="[^"]*\.ru(@[^"]*)?"', re.I)
RU_COUNTRY = re.compile(
    r'tvg-country="(?:RU|RUS|RUSSIA|РОССИЯ)"', re.I
)
RU_GROUP = re.compile(
    r'group-title="(?:Russia|Russian|Русские|Россия|Русский)"', re.I
)
RU_LANGUAGE = re.compile(
    r'tvg-language="[^"]*(?:Russian|Русский|русский|rus)[^"]*"', re.I
)


def fetch(url, retries=3):
    req = urllib.request.Request(
        url,
        headers={"User-Agent": USER_AGENT}
    )

    for attempt in range(1, retries + 1):
        try:
            with urllib.request.urlopen(req, timeout=40) as response:
                data = response.read()
                return data.decode("utf-8-sig", errors="replace")

        except Exception as exc:
            if attempt == retries:
                print(f"ОШИБКА загрузки: {exc}")
                return None

            time.sleep(2 * attempt)

    return None


def parse(text):
    """Сохраняет все служебные строки перед адресом потока."""
    meta = []

    for raw in text.splitlines():
        line = raw.strip()

        if not line:
            continue

        if line.upper().startswith("#EXTM3U"):
            continue

        if line.startswith("#PLAYLIST"):
            continue

        if line.startswith("#"):
            meta.append(line)

        else:
            if meta and meta[0].upper().startswith("#EXTINF"):
                yield meta, line

            meta = []


def is_russian(meta):
    """Проверяет язык, страну и другие признаки канала."""
    joined = "\n".join(meta)

    return bool(
        RU_ID.search(joined)
        or RU_COUNTRY.search(joined)
        or RU_GROUP.search(joined)
        or RU_LANGUAGE.search(joined)
    )


def split_extinf(line):
    """Разделяет описание и название канала."""
    quoted = False

    for i, ch in enumerate(line):
        if ch == '"':
            quoted = not quoted

        elif ch == "," and not quoted:
            return line[:i], line[i + 1:]

    return line, ""


def canonical_group(old):
    for name, pattern in GROUP_RULES:
        if re.search(pattern, old, re.I):
            return name

    return "Разное"


def regroup(meta):
    head, name = split_extinf(meta[0])

    if NAME_DROP.search(name):
        return None

    match = GROUP_RE.search(head)
    old = match.group(1) if match else ""

    group = canonical_group(old)

    if group == "DROP":
        return None

    if match:
        head = GROUP_RE.sub(
            f'group-title="{group}"',
            head,
            count=1
        )
    else:
        head = head.rstrip() + f' group-title="{group}"'

    rest = [
        line for line in meta[1:]
        if not line.upper().startswith("#EXTGRP")
    ]

    return [head + "," + name] + rest, group, old


def read_sources():
    sources = []

    with open(SOURCES_FILE, encoding="utf-8") as file:
        for raw in file:
            line = raw.strip()

            if not line or line.startswith("#"):
                continue

            url, _, flag = line.partition("|")

            sources.append((
                url.strip(),
                flag.strip().lower() == "ru"
            ))

    return sources


def main():
    sources = read_sources()

    entries = []
    seen_variants = set()
    failed = 0

    for i, (url, ru_only) in enumerate(sources, 1):
        print(f"\nИсточник {i}/{len(sources)}:")
        print(url)

        text = fetch(url)

        if text is None:
            failed += 1
            print("FAILED: источник недоступен")
            continue

        total = 0
        added = 0
        filtered = 0
        duplicates = 0

        for meta, stream in parse(text):
            total += 1

            if BAD_URL.search(stream):
                filtered += 1
                continue

            if ru_only and not is_russian(meta):
                filtered += 1
                continue

            result = regroup(meta)

            if result is None:
                filtered += 1
                continue

            lines, group, old = result

            # Не теряем варианты одного потока с разными
            # настройками User-Agent, Referer и KODIPROP.
            directives = tuple(
                line for line in lines[1:]
                if line.upper().startswith((
                    "#EXTVLCOPT",
                    "#KODIPROP",
                    "#EXTHTTP"
                ))
            )

            key = (stream, directives)

            if key in seen_variants:
                duplicates += 1
                continue

            seen_variants.add(key)
            entries.append((group, lines + [stream]))
            added += 1

        print(
            f"Прочитано: {total}; "
            f"добавлено: {added}; "
            f"отфильтровано: {filtered}; "
            f"дубликатов: {duplicates}"
        )

    print("\n========== ИТОГ ==========")
    print(f"Источников: {len(sources)}")
    print(f"Недоступных источников: {failed}")
    print(f"Уникальных вариантов каналов: {len(seen_variants)}")

    if len(entries) < MIN_ENTRIES:
        print(
            f"ОШИБКА: меньше {MIN_ENTRIES} записей. "
            "Старый all.m3u сохранён."
        )
        return 1

    rank = {
        group: i
        for i, group in enumerate(GROUP_ORDER)
    }

    entries.sort(
        key=lambda entry: rank.get(entry[0], 99)
    )

    counts = {}

    for group, _ in entries:
        counts[group] = counts.get(group, 0) + 1

    print("\nКаналов по папкам:")

    for group in GROUP_ORDER:
        if group in counts:
            print(f"{group}: {counts[group]}")

    body = [
        line
        for _, lines in entries
        for line in lines
    ]

    temp_file = OUTPUT_FILE + ".tmp"

    with open(temp_file, "w", encoding="utf-8") as file:
        file.write("#EXTM3U\n")
        file.write("\n".join(body))
        file.write("\n")

    os.replace(temp_file, OUTPUT_FILE)

    print("\nSUCCESS: all.m3u успешно создан.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
