#!/usr/bin/env python3
"""Собирает all.m3u из sources.txt.

- строки sources.txt: "URL" или "URL | ru" (оставить только российские каналы)
- у каждого канала сохраняются ВСЕ служебные строки (#EXTVLCOPT, #KODIPROP...),
  иначе потоки, которым нужен User-Agent или Referer, не открываются
- дубли убираются по адресу потока
- упавший источник пропускается, но если каналов меньше MIN_ENTRIES,
  старый all.m3u остаётся нетронутым
- десятки разных "папок" (group-title) сводятся к ~10 понятным, см. GROUP_RULES;
  телемагазины выбрасываются
"""
import re
import sys
import time
import urllib.request

SOURCES_FILE = "sources.txt"
OUTPUT_FILE = "all.m3u"
MIN_ENTRIES = 300
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
# Ссылки, которые IPTV-плеер открыть не может (это страницы, а не потоки)
BAD_URL = re.compile(
    r"^(rtsp:|rtmp:)|youtube\.com|youtu\.be|twitch\.tv|dailymotion\.com",
    re.I,
)
# Порядок важен: берётся первое совпадение. Слева название папки, справа
# регулярное выражение (по названию исходной папки, без учёта регистра).
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
GROUP_ORDER = ["Федеральные", "Новости", "Кино и сериалы", "Спорт", "Музыка",
               "Детские", "Познавательные", "Региональные", "Религия", "18+", "Разное"]
NAME_DROP = re.compile(r"teleshop|телемагазин|shopping|\bqvc\b|\bhsn\b", re.I)
GROUP_RE = re.compile(r'group-title="([^"]*)"', re.I)
RU_ID = re.compile(r'tvg-id="[^"]*\.ru(@[^"]*)?"', re.I)
RU_COUNTRY = re.compile(r'tvg-country="RU"', re.I)
RU_GROUP = re.compile(r'group-title="Russia"', re.I)


def fetch(url, retries=3):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    for attempt in range(1, retries + 1):
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return resp.read().decode("utf-8-sig", errors="replace")
        except Exception as exc:
            if attempt == retries:
                print(f"  failed after {retries} attempts: {exc}")
                return None
            time.sleep(2 * attempt)
    return None


def parse(text):
    """Отдаёт (строки_описания, адрес). Описание = все строки # перед адресом."""
    meta = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.upper().startswith("#EXTM3U") or line.startswith("#PLAYLIST"):
            continue
        if line.startswith("#"):
            meta.append(line)
        else:
            if meta and meta[0].upper().startswith("#EXTINF"):
                yield meta, line
            meta = []


def is_russian(meta):
    head = meta[0]
    return bool(RU_ID.search(head) or RU_COUNTRY.search(head) or RU_GROUP.search(head))


def split_extinf(line):
    """Делит #EXTINF на описание и название по первой запятой вне кавычек."""
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
    """Возвращает (новые строки, папка) или None, если канал надо выбросить."""
    head, name = split_extinf(meta[0])
    if NAME_DROP.search(name):
        return None
    match = GROUP_RE.search(head)
    old = match.group(1) if match else ""
    group = canonical_group(old)
    if group == "DROP":
        return None
    if match:
        head = GROUP_RE.sub(f'group-title="{group}"', head, count=1)
    else:
        head = head.rstrip() + f' group-title="{group}" '
    rest = [m for m in meta[1:] if not m.upper().startswith("#EXTGRP")]
    return [head + "," + name] + rest, group, old


def read_sources():
    sources = []
    with open(SOURCES_FILE, encoding="utf-8") as f:
        for raw in f:
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            url, _, flag = line.partition("|")
            sources.append((url.strip(), flag.strip().lower() == "ru"))
    return sources


def main():
    sources = read_sources()
    seen, entries, failed = set(), [], 0
    misc = {}
    for i, (url, ru_only) in enumerate(sources, 1):
        text = fetch(url)
        if text is None:
            failed += 1
            print(f"FAILED {i}/{len(sources)}: {url}")
            continue
        total = added = 0
        for meta, stream in parse(text):
            total += 1
            if BAD_URL.search(stream):
                continue
            if ru_only and not is_russian(meta):
                continue
            if stream in seen:
                continue
            res = regroup(meta)
            if res is None:
                continue
            lines, group, old = res
            seen.add(stream)
            entries.append((group, lines + [stream]))
            if group == "Разное":
                misc[old or "(без папки)"] = misc.get(old or "(без папки)", 0) + 1
            added += 1
        print(f"OK {i}/{len(sources)}: read {total}, added {added} - {url}")

    print(f"Unique channels: {len(seen)}; failed sources: {failed}")
    if len(seen) < MIN_ENTRIES:
        print(f"ERROR: меньше {MIN_ENTRIES} каналов, all.m3u не тронут.")
        return 1
    rank = {g: i for i, g in enumerate(GROUP_ORDER)}
    entries.sort(key=lambda e: rank.get(e[0], 99))  # сортировка устойчивая
    counts = {}
    for group, _ in entries:
        counts[group] = counts.get(group, 0) + 1
    print("Папки:", ", ".join(f"{g}={counts[g]}" for g in GROUP_ORDER if g in counts))
    if misc:
        top = sorted(misc.items(), key=lambda kv: -kv[1])[:25]
        print("В 'Разное' попали папки:", "; ".join(f"{k}={v}" for k, v in top))
    body = [line for _, lines in entries for line in lines]
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write("#EXTM3U\n" + "\n".join(body) + "\n")
    print(f"SUCCESS: {OUTPUT_FILE} записан.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
