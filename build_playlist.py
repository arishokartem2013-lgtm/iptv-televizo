
#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Сборка all.m3u из sources.txt с резервной загрузкой SMOLNP."""

import os
import re
import sys
import time
import json
import base64
import urllib.request
import urllib.error
import urllib.parse

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
    (
        "Кино и сериалы",
        r"movie|film|cinema|кино|фильм|сериал|series|comed|комед|драм|"
        r"drama|thriller|horror|триллер|ужас|боевик|мелодрам"
    ),
    (
        "Познавательные",
        r"document|educat|science|познават|образоват|наук|хобби|"
        r"lifestyle|outdoor|travel|cooking|nature|culture|культур|"
        r"histor|истори|weather|auto|авто"
    ),
    (
        "Федеральные",
        r"general|entertainment|развлек|общественн|эфир|public|"
        r"federal|федеральн|interactive"
    ),
]

GROUP_ORDER = [
    "Федеральные",
    "Новости",
    "Кино и сериалы",
    "Спорт",
    "Музыка",
    "Детские",
    "Познавательные",
    "Региональные",
    "Религия",
    "18+",
    "Разное"
]

NAME_DROP = re.compile(
    r"teleshop|телемагазин|shopping|\bqvc\b|\bhsn\b",
    re.I
)

GROUP_RE = re.compile(r'group-title="([^"]*)"', re.I)


def request_text(url):
    """Загружает текст по URL."""

    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "*/*"
        }
    )

    with urllib.request.urlopen(req, timeout=60) as response:
        data = response.read()

    return data.decode("utf-8-sig", errors="replace")


def valid_playlist(text):
    """Проверяет, что сервер вернул настоящий M3U."""

    return (
        text
        and "#EXTINF" in text
        and ("#EXTM3U" in text or "#PLAYLIST" in text)
    )


def fetch_smolnp(url):
    """Загрузка SMOLNP через несколько независимых серверов."""

    path = urllib.parse.urlsplit(url).path
    filename = urllib.parse.unquote(path.rsplit("/", 1)[-1])
    encoded = urllib.parse.quote(filename, safe="")

    print(f"SMOLNP: файл {filename}")
    print("Проверяю резервные серверы...")

    mirrors = [
        (
            "jsDelivr",
            f"https://cdn.jsdelivr.net/gh/smolnp/IPTVru@gh-pages/{encoded}"
        ),
        (
            "Raw Githack",
            f"https://raw.githack.com/smolnp/IPTVru/gh-pages/{encoded}"
        ),
        (
            "GitHub Pages",
            f"https://smolnp.github.io/IPTVru//{encoded}"
        ),
        (
            "GitHub Pages 2",
            f"https://smolnp.github.io/IPTVru/{encoded}"
        ),
        (
            "GitHub Raw",
            f"https://raw.githubusercontent.com/smolnp/IPTVru/refs/heads/gh-pages/{encoded}"
        )
    ]

    for name, mirror_url in mirrors:
        try:
            print(f"Пробую {name}...")

            text = request_text(mirror_url)

            if valid_playlist(text):
                print(f"SMOLNP УСПЕШНО ЗАГРУЖЕН: {name}")
                return text

            print(f"{name}: получен не M3U файл")

        except Exception as exc:
            print(f"{name}: {exc}")

    # Последняя попытка через GitHub API.
    print("Пробую GitHub API...")

    api_url = (
        "https://api.github.com/repos/smolnp/IPTVru/contents/"
        + encoded
        + "?ref=gh-pages"
    )

    try:
        req = urllib.request.Request(
            api_url,
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28"
            }
        )

        with urllib.request.urlopen(req, timeout=60) as response:
            payload = json.loads(
                response.read().decode("utf-8")
            )

        if payload.get("encoding") == "base64":
            content = base64.b64decode(payload["content"])
            text = content.decode("utf-8-sig", errors="replace")

            if valid_playlist(text):
                print("SMOLNP УСПЕШНО ЗАГРУЖЕН: GitHub API")
                return text

        if payload.get("download_url"):
            text = request_text(payload["download_url"])

            if valid_playlist(text):
                print("SMOLNP УСПЕШНО ЗАГРУЖЕН: download_url")
                return text

    except Exception as exc:
        print(f"GitHub API: {exc}")

    print("Все способы загрузки SMOLNP исчерпаны.")
    return None


def fetch(url, retries=3):
    """Загрузка обычного источника и SMOLNP."""

    if "smolnp/IPTVru/" in url:
        return fetch_smolnp(url)

    last_error = None

    for attempt in range(1, retries + 1):
        try:
            return request_text(url)

        except Exception as exc:
            last_error = exc
            print(f"Попытка {attempt}/{retries}: {exc}")

            if attempt < retries:
                time.sleep(2 * attempt)

    print(f"ОШИБКА загрузки: {last_error}")
    return None


def parse(text):
    """Сохраняет служебные строки перед адресом потока."""

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

            result = regroup(meta)

            if result is None:
                filtered += 1
                continue

            lines, group, old = result

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
