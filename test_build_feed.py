import json
import os
import unittest

import build_feed as bf

HERE = os.path.dirname(os.path.abspath(__file__))
BLOCKLIST = bf.compile_blocklist(json.load(open(os.path.join(HERE, "blocklist.json"), encoding="utf-8"))["keywords"])


def video(**over):
    v = {
        "id": "abc123def45",
        "snippet": {"channelId": "UCx", "title": "Pepee ile renkleri öğreniyoruz", "publishedAt": "2026-09-01T10:00:00Z",
                    "liveBroadcastContent": "none"},
        "contentDetails": {"duration": "PT58S"},
        "status": {"madeForKids": True, "embeddable": True, "privacyStatus": "public", "uploadStatus": "processed"},
        "player": {"embedWidth": "405", "embedHeight": "720"},
    }
    for path, value in over.items():
        section, key = path.split("__")
        v[section][key] = value
    return v


class ParseDuration(unittest.TestCase):
    def test_formats(self):
        self.assertEqual(bf.parse_duration("PT58S"), 58)
        self.assertEqual(bf.parse_duration("PT3M5S"), 185)
        self.assertEqual(bf.parse_duration("PT1H"), 3600)
        self.assertEqual(bf.parse_duration("P0D"), 0)
        self.assertEqual(bf.parse_duration("garbage"), 0)
        self.assertEqual(bf.parse_duration(None), 0)


class Blocklist(unittest.TestCase):
    def blocked(self, title):
        return bool(BLOCKLIST.search(bf.fold(title)))

    def test_turkish_folding(self):
        self.assertTrue(self.blocked("KORKUNÇ Orman"))
        self.assertTrue(self.blocked("Hayaletli ev"))
        self.assertTrue(self.blocked("Cadılar Bayramı şarkısı"))

    def test_whole_word_only(self):
        self.assertFalse(self.blocked("Pepee kanal şarkısı"))       # 'kan' is a whole word only
        self.assertTrue(self.blocked("kan çıktı"))
        self.assertFalse(self.blocked("Warm hugs song"))            # 'war' must not hit 'warm'
        self.assertFalse(self.blocked("Kurabiye Canavarı ile sayılar"))
        self.assertFalse(self.blocked("Guntur and friends"))

    def test_english_and_trends(self):
        self.assertTrue(self.blocked("Scary Monster Prank!!"))
        self.assertTrue(self.blocked("Skibidi toilet song"))
        self.assertTrue(self.blocked("Huggy Wuggy dance"))
        self.assertFalse(self.blocked("Wheels on the Bus | Nursery Rhymes"))


class RejectReason(unittest.TestCase):
    def test_good_video_passes(self):
        self.assertIsNone(bf.reject_reason(video(), BLOCKLIST))

    def test_rules(self):
        cases = {
            "not-made-for-kids": video(status__madeForKids=False),
            "not-embeddable": video(status__embeddable=False),
            "not-public": video(status__privacyStatus="unlisted"),
            "live": video(snippet__liveBroadcastContent="upcoming"),
            "region-restricted": video(contentDetails__regionRestriction={"blocked": ["TR"]}),
            "age-restricted": video(contentDetails__contentRating={"ytRating": "ytAgeRestricted"}),
            "duration": video(contentDetails__duration="PT12M"),
            "blocklist": video(snippet__title="Scary ghost story"),
        }
        for expected, v in cases.items():
            self.assertEqual(bf.reject_reason(v, BLOCKLIST), expected)

    def test_missing_made_for_kids_is_rejected(self):
        v = video()
        del v["status"]["madeForKids"]
        self.assertEqual(bf.reject_reason(v, BLOCKLIST), "not-made-for-kids")


class FakeYouTube:
    """Minimal stand-in for bf.YouTube used to exercise build()."""

    def __init__(self, videos_by_channel, missing_shorts=()):
        self.videos_by_channel = videos_by_channel
        self.missing_shorts = set(missing_shorts)
        self.units = 0

    def channel_thumbnails(self, ids):
        return {i: f"https://thumb/{i}" for i in ids}

    def channel_video_ids(self, channel_id):
        return [v["id"] for v in self.videos_by_channel.get(channel_id, [])]

    def videos(self, ids):
        allv = [v for vs in self.videos_by_channel.values() for v in vs]
        return [v for v in allv if v["id"] in ids]


class Build(unittest.TestCase):
    def test_build_filters_and_shapes_output(self):
        good = video()
        good["id"] = "good0000001"
        good["snippet"]["channelId"] = "UCa"
        bad = video(status__madeForKids=False)
        bad["id"] = "bad00000001"
        bad["snippet"]["channelId"] = "UCa"
        wide = video(player__embedWidth="1280", player__embedHeight="720")
        wide["id"] = "wide0000001"
        wide["snippet"]["channelId"] = "UCa"
        catalog = {"channels": [
            {"id": "UCa", "name": "A", "lang": "tr", "enabledByDefault": True},
            {"id": "UCb", "name": "B", "lang": "en", "enabledByDefault": False},
        ]}
        feed = bf.build(FakeYouTube({"UCa": [good, bad, wide]}), catalog, BLOCKLIST, log=lambda *_: None)
        self.assertEqual([c["id"] for c in feed["channels"]], ["UCa"])  # empty channel B omitted
        ids = {v["id"]: v for v in feed["videos"]}
        self.assertEqual(set(ids), {"good0000001", "wide0000001"})
        self.assertTrue(ids["good0000001"]["vertical"])
        self.assertFalse(ids["wide0000001"]["vertical"])
        self.assertEqual(ids["good0000001"]["durationSec"], 58)
        self.assertEqual(feed["schemaVersion"], 1)


if __name__ == "__main__":
    unittest.main()
