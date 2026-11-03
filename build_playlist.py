import os
import re
import sys
import time
import urllib.error
import urllib.request

SOURCES_FILE = "sources.txt"
OUTPUT_FILE = "all.m3u"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


def fetch_url(url, retries=3, delay=2):
  headers = {"User-Agent": USER_AGENT}
  req = urllib.request.Request(url, headers=headers)

  for attempt in range(1, retries + 1):
    try:
      with urllib.request.urlopen(req, timeout=25) as response:
        content = response.read().decode("utf-8", errors="ignore")
        return content
    except Exception as e:
      if attempt == retries:
        print(f" – failed after {retries} attempts: {e}")
        return None
      time.sleep(delay)
  return None


def parse_m3u(content, ru_only=False):
  channels = []
  current_extinf = None

  for line in content.splitlines():
    line = line.strip()
    if not line:
      continue

    if line.startswith("#EXTINF:"):
      current_extinf = line
    elif not line.startswith("#") and current_extinf:
      stream_url = line

      # Если для источника задан флаг "| ru"
      if ru_only:
        tvg_id_match = re.search(r'tvg-id="([^"]+)"', current_extinf, re.I)
        is_ru_id = bool(
            tvg_id_match and tvg_id_match.group(1).lower().endswith(".ru")
        )
        is_ru_group = bool(
            re.search(r'group-title="[^"]*ru[^"]*"', current_extinf, re.I)
        )

        if not (is_ru_id or is_ru_group):
          current_extinf = None
          continue

      channels.append({"extinf": current_extinf, "url": stream_url})
      current_extinf = None

  return channels


def main():
  if not os.path.exists(SOURCES_FILE):
    print(f"File {SOURCES_FILE} not found!")
    sys.exit(1)

  with open(SOURCES_FILE, "r", encoding="utf-8") as f:
    lines = [line.strip() for line in f if line.strip()]

  sources = []
  for line in lines:
    if line.startswith("#"):
      continue
    parts = [p.strip() for p in line.split("|")]
    url = parts[0]
    ru_only = len(parts) > 1 and parts[1].lower() == "ru"
    sources.append((url, ru_only))

  all_channels = []
  seen_urls = set()
  failed_sources = 0
  total = len(sources)

  for idx, (url, ru_only) in enumerate(sources, 1):
    prefix = f"{idx}/{total}: {url}"
    content = fetch_url(url)

    if content is None:
      print(f"FAILED {prefix}")
      failed_sources += 1
      continue

    channels = parse_m3u(content, ru_only=ru_only)
    added = 0
    for ch in channels:
      # Дедупликация потоков
      if ch["url"] not in seen_urls:
        seen_urls.add(ch["url"])
        all_channels.append(ch)
        added += 1

    print(f"OK {idx}/{total}: read {len(channels)}, added {added} – {url}")

  print(f"Unique channels: {len(all_channels)}")

  if not all_channels:
    print("ERROR: No channels collected from any source.")
    sys.exit(1)

  # Сохраняем собранный плейлист
  with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
    f.write("#EXTM3U\n")
    for ch in all_channels:
      f.write(f"{ch['extinf']}\n{ch['url']}\n")

  if failed_sources > 0:
    print(
        f"WARNING: {failed_sources} source(s) failed, but {OUTPUT_FILE} was successfully updated with available channels."
    )
  else:
    print(f"SUCCESS: {OUTPUT_FILE} successfully generated.")


if __name__ == "__main__":
  main()
