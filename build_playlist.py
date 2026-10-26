#!/usr/bin/env python3
"""Download M3U sources, filter/deduplicate entries by stream URL, write all.m3u."""
from pathlib import Path
from urllib.request import Request, urlopen
import re
import sys
import time

ROOT = Path(__file__).resolve().parent
SOURCES_FILE = ROOT / "sources.txt"
OUTPUT_FILE = ROOT / "all.m3u"
MIN_ENTRIES = 300          # reject the build if fewer unique channels than this
TIMEOUT_SECONDS = 45
RETRIES = 3
USER_AGENT = "IPTV-M3U-Combiner/1.1 (+GitHub Actions)"
RU_FILTER = re.compile(r'\.ru[@"]', re.IGNORECASE)   # tvg-id like Channel.ru@SD


def fetch(url):
    last = None
    for attempt in range(1, RETRIES + 1):
        try:
            req = Request(url, headers={"User-Agent": USER_AGENT})
            with urlopen(req, timeout=TIMEOUT_SECONDS) as resp:
                data = resp.read()
            return data.decode("utf-8-sig", errors="replace")
        except Exception as exc:
            last = exc
            time.sleep(2 * attempt)
    raise RuntimeError(f"failed after {RETRIES} attempts: {last}")


def parse_entries(text):
    """Yield (meta_lines, url) pairs. Meta = all '#' lines before the URL."""
    meta = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.upper().startswith("#EXTM3U"):
            continue
        if line.startswith("#"):
            meta.append(line)
        else:
            yield meta, line
            meta = []


def read_sources():
    out = []
    for raw in SOURCES_FILE.read_text(encoding="utf-8").splitlines():
        raw = raw.strip()
        if not raw or raw.startswith("#"):
            continue
        url, _, flag = raw.partition("|")
        out.append((url.strip(), flag.strip().lower() == "ru"))
    return out


def main():
    sources = read_sources()
    if not sources:
        print("ERROR: sources.txt is empty.")
        return 1

    seen, body, failures = set(), [], []
    for i, (url, ru_only) in enumerate(sources, 1):
        try:
            text = fetch(url)
            total = kept = 0
            for meta, stream in parse_entries(text):
                total += 1
                if ru_only and not RU_FILTER.search("\n".join(meta)):
                    continue
                if stream in seen:
                    continue
                seen.add(stream)
                body.extend(meta + [stream])
                kept += 1
            if total == 0:
                raise RuntimeError("not a valid M3U (no channels found)")
            print(f"OK {i}/{len(sources)}: read {total}, added {kept} — {url}")
        except Exception as exc:
            failures.append((url, str(exc)))
            print(f"FAILED {i}/{len(sources)}: {url} — {exc}")

    unique = len(seen)
    print(f"Unique channels: {unique}")
    if failures:
        print("ERROR: some sources failed; keeping the previous all.m3u.")
        return 1
    if unique < MIN_ENTRIES:
        print(f"ERROR: {unique} < MIN_ENTRIES={MIN_ENTRIES}; build rejected.")
        return 1

    OUTPUT_FILE.write_text("\n".join(["#EXTM3U"] + body) + "\n", encoding="utf-8")
    print(f"SUCCESS: wrote {OUTPUT_FILE.name} with {unique} channels.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
