#!/usr/bin/env python3
"""Builds feed.json for Pofi TV from the curated channel catalog.

Only the YouTube Data API v3 is used (no scraping). Quota cost per run is roughly
2-4 units per channel, independent of how many TVs use the app.

Usage:
  YOUTUBE_API_KEY=... python3 build_feed.py --out site/feed.json
  (or put YOUTUBE_API_KEY=... into a local .env file next to this script)
"""

import argparse
import datetime as dt
import json
import os
import re
import sys
import unicodedata
import urllib.error
import urllib.parse
import urllib.request

API = "https://www.googleapis.com/youtube/v3/"
HERE = os.path.dirname(os.path.abspath(__file__))

MAX_DURATION_SEC = 240
MIN_DURATION_SEC = 8
PER_CHANNEL_LIMIT = 60
PAGES_PER_PLAYLIST = 2
MIN_TOTAL_VIDEOS = 40  # below this something is wrong; fail so the last good feed stays online


class ApiError(Exception):
    def __init__(self, status, reason):
        super().__init__(f"{status} {reason}")
        self.status = status
        self.reason = reason


# ---------- pure helpers (unit tested) ----------

def fold(text):
    """Lowercase and strip Turkish/Latin diacritics so 'KORKUNÇ' == 'korkunc'."""
    text = text.replace("İ", "i").replace("I", "i").replace("ı", "i")
    text = unicodedata.normalize("NFKD", text.lower())
    return "".join(c for c in text if not unicodedata.combining(c))


def compile_blocklist(keywords):
    parts = []
    for kw in keywords:
        prefix = kw.endswith("*")
        word = re.escape(fold(kw.rstrip("*")))
        parts.append(r"(?<![a-z0-9])" + word + ("" if prefix else r"(?![a-z0-9])"))
    return re.compile("|".join(parts)) if parts else None


def parse_duration(iso):
    """ISO-8601 duration (PT1M5S, P0D, PT1H) -> seconds."""
    m = re.fullmatch(r"P(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?)?", iso or "")
    if not m:
        return 0
    d, h, mi, s = (int(x or 0) for x in m.groups())
    return ((d * 24 + h) * 60 + mi) * 60 + s


def reject_reason(video, blocklist):
    """Returns why a videos.list item must not be shown, or None if it is fine."""
    status = video.get("status", {})
    snippet = video.get("snippet", {})
    details = video.get("contentDetails", {})
    if status.get("madeForKids") is not True:
        return "not-made-for-kids"
    if status.get("embeddable") is not True:
        return "not-embeddable"
    if status.get("privacyStatus") != "public" or status.get("uploadStatus") != "processed":
        return "not-public"
    if snippet.get("liveBroadcastContent", "none") != "none" or "liveStreamingDetails" in video:
        return "live"
    region = details.get("regionRestriction") or {}
    if "allowed" in region and not region["allowed"]:
        return "region-restricted"  # allowed nowhere
    if details.get("contentRating", {}).get("ytRating") == "ytAgeRestricted":
        return "age-restricted"
    duration = parse_duration(details.get("duration"))
    if not MIN_DURATION_SEC <= duration <= MAX_DURATION_SEC:
        return "duration"
    if blocklist is not None and blocklist.search(fold(snippet.get("title", ""))):
        return "blocklist"
    return None


def to_feed_video(video):
    snippet = video["snippet"]
    player = video.get("player", {})
    w, h = int(player.get("embedWidth") or 16), int(player.get("embedHeight") or 9)
    item = {
        "id": video["id"],
        "channelId": snippet["channelId"],
        "title": snippet.get("title", ""),
        "durationSec": parse_duration(video["contentDetails"]["duration"]),
        "vertical": h > w,
        "publishedAt": snippet.get("publishedAt", ""),
    }
    # Country rules stay in the feed; the app checks them against the TV's country.
    region = video["contentDetails"].get("regionRestriction") or {}
    if "allowed" in region:
        item["allowed"] = sorted(region["allowed"])
    elif region.get("blocked"):
        item["blocked"] = sorted(region["blocked"])
    return item


# ---------- YouTube API ----------

class YouTube:
    def __init__(self, key):
        self.key = key
        self.units = 0

    def get(self, endpoint, **params):
        params["key"] = self.key
        url = API + endpoint + "?" + urllib.parse.urlencode(params)
        self.units += 1
        try:
            with urllib.request.urlopen(url, timeout=30) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            try:
                reason = json.load(e)["error"]["errors"][0]["reason"]
            except Exception:
                reason = e.reason
            raise ApiError(e.code, reason) from None

    def playlist_video_ids(self, playlist_id):
        ids, token = [], None
        for _ in range(PAGES_PER_PLAYLIST):
            params = {"part": "contentDetails", "playlistId": playlist_id, "maxResults": 50,
                      "fields": "nextPageToken,items/contentDetails/videoId"}
            if token:
                params["pageToken"] = token
            data = self.get("playlistItems", **params)
            ids += [it["contentDetails"]["videoId"] for it in data.get("items", [])]
            token = data.get("nextPageToken")
            if not token:
                break
        return ids

    def channel_video_ids(self, channel_id):
        """Shorts (UUSH) + regular uploads (UULF); falls back to all uploads (UU)."""
        suffix = channel_id[2:]
        ids = []
        for prefix in ("UUSH", "UULF"):
            try:
                ids += self.playlist_video_ids(prefix + suffix)
            except ApiError as e:
                if e.status != 404:
                    raise
        if not ids:
            ids = self.playlist_video_ids("UU" + suffix)
        return list(dict.fromkeys(ids))

    def videos(self, ids):
        out = []
        for i in range(0, len(ids), 50):
            data = self.get("videos", part="snippet,contentDetails,status,player,liveStreamingDetails",
                            id=",".join(ids[i:i + 50]), maxHeight=720)
            out += data.get("items", [])
        return out

    def channel_thumbnails(self, channel_ids):
        thumbs = {}
        for i in range(0, len(channel_ids), 50):
            data = self.get("channels", part="snippet", id=",".join(channel_ids[i:i + 50]),
                            fields="items(id,snippet/thumbnails/default/url)")
            for it in data.get("items", []):
                thumbs[it["id"]] = it["snippet"]["thumbnails"]["default"]["url"]
        return thumbs


def load_key():
    key = os.environ.get("YOUTUBE_API_KEY")
    env_file = os.path.join(HERE, ".env")
    if not key and os.path.exists(env_file):
        for line in open(env_file, encoding="utf-8"):
            if line.strip().startswith("YOUTUBE_API_KEY="):
                key = line.split("=", 1)[1].strip().strip('"\'')
    if not key:
        sys.exit("YOUTUBE_API_KEY is not set (env var or .env file).")
    return key


def build(yt, catalog, blocklist, log=print):
    channels = catalog["channels"]
    thumbs = yt.channel_thumbnails([c["id"] for c in channels])
    feed_channels, feed_videos = [], []
    for ch in channels:
        try:
            ids = yt.channel_video_ids(ch["id"])
            items = yt.videos(ids)
        except ApiError as e:
            if e.reason in ("quotaExceeded", "keyInvalid", "forbidden"):
                raise
            log(f"  ! {ch['name']}: {e} (skipped)")
            continue
        reasons = {}
        kept = []
        for v in items:
            if v.get("snippet", {}).get("channelId") != ch["id"]:
                reasons["foreign-channel"] = reasons.get("foreign-channel", 0) + 1
                continue
            why = reject_reason(v, blocklist)
            if why:
                reasons[why] = reasons.get(why, 0) + 1
            else:
                kept.append(to_feed_video(v))
        kept.sort(key=lambda v: v["publishedAt"], reverse=True)
        kept = kept[:PER_CHANNEL_LIMIT]
        log(f"  {ch['name']:<22} candidates={len(items):>3} kept={len(kept):>3} dropped={reasons}")
        if not kept:
            continue
        feed_channels.append({
            "id": ch["id"], "name": ch["name"], "lang": ch["lang"],
            "enabledByDefault": ch.get("enabledByDefault", True),
            "thumbnail": thumbs.get(ch["id"], ""),
        })
        feed_videos += kept
    return {
        "schemaVersion": 1,
        "generatedAt": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "channels": feed_channels,
        "videos": feed_videos,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(HERE, "site", "feed.json"))
    args = ap.parse_args()

    catalog = json.load(open(os.path.join(HERE, "channels.json"), encoding="utf-8"))
    blocklist = compile_blocklist(json.load(open(os.path.join(HERE, "blocklist.json"), encoding="utf-8"))["keywords"])
    yt = YouTube(load_key())

    feed = build(yt, catalog, blocklist)
    total = len(feed["videos"])
    print(f"channels={len(feed['channels'])} videos={total} quota_units~{yt.units}")
    if total < MIN_TOTAL_VIDEOS:
        sys.exit(f"Only {total} videos, refusing to publish.")

    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(feed, f, ensure_ascii=False, separators=(",", ":"))


if __name__ == "__main__":
    main()
