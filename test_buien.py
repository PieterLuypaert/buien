"""Tests for buien. Run with: python3 -m unittest"""
import contextlib
import importlib.machinery
import importlib.util
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
import urllib.error
from datetime import datetime, timedelta, timezone
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
_loader = importlib.machinery.SourceFileLoader("buien", os.path.join(HERE, "buien"))
buien = importlib.util.module_from_spec(importlib.util.spec_from_loader("buien", _loader))
sys.modules["buien"] = buien
_loader.exec_module(buien)

_module_patches = contextlib.ExitStack()


def setUpModule():
    """Keeps every test away from the real cache in ~/.cache."""
    cache = _module_patches.enter_context(tempfile.TemporaryDirectory())
    _module_patches.enter_context(mock.patch.dict(os.environ, {"XDG_CACHE_HOME": cache}))


def tearDownModule():
    _module_patches.close()


START = datetime(2026, 10, 13, 12, 30).astimezone()
GENT = buien.Place("Gent", 51.05, 3.72)


def slots(*mm):
    return [buien.Slot(START + index * buien.STEP, value) for index, value in enumerate(mm)]


def plain(text):
    return buien.ANSI.sub("", text)


class SummaryTest(unittest.TestCase):
    def test_dry_all_the_way(self):
        self.assertEqual(buien.summarize(slots(0, 0, 0, 0)), "dry until at least 12:50")

    def test_rain_on_the_way(self):
        forecast = slots(0, 0, 0.8, 1.2, 0.6, 0, 0, 0)
        self.assertEqual(buien.summarize(forecast), "dry until 12:40, then 15 min of light rain")

    def test_rain_now_that_stops(self):
        forecast = slots(3, 2.5, 0, 0, 0)
        self.assertEqual(buien.summarize(forecast), "moderate rain now, dry from 12:40")

    def test_rain_now_past_the_horizon(self):
        self.assertEqual(buien.summarize(slots(0.2, 0.3, 0.1)), "drizzle now, not dry before 12:45")

    def test_rain_that_starts_and_does_not_stop(self):
        self.assertEqual(buien.summarize(slots(0, 0, 6, 8)), "dry until 12:40, then heavy rain")

    def test_a_range_of_intensities(self):
        forecast = slots(0, 0.1, 1, 4, 12, 3, 0.2, 0, 0)
        self.assertEqual(buien.summarize(forecast), "dry until 12:35, then 30 min of light to very heavy rain")

    def test_a_second_shower(self):
        forecast = slots(0, 1, 1, 0, 0, 0, 0.2, 0.3, 0)
        self.assertEqual(
            buien.summarize(forecast),
            "dry until 12:35, then 10 min of light rain, more drizzle around 13:00",
        )

    def test_a_dry_gap_of_five_minutes_does_not_end_the_spell(self):
        forecast = slots(1, 1, 0, 1, 0, 0, 0)
        self.assertEqual(buien.summarize(forecast), "light rain now, dry from 12:50")

    def test_long_spells_in_hours(self):
        self.assertEqual(buien.duration(25), "25 min")
        self.assertEqual(buien.duration(60), "1 hour")
        self.assertEqual(buien.duration(90), "1h30")
        self.assertEqual(buien.duration(120), "2 hours")

    def test_peak(self):
        self.assertEqual(buien.peak(slots(0, 2.4, 1)), "heaviest at 12:35: 2.4 mm per hour")
        self.assertIsNone(buien.peak(slots(0, 0)))


class KindTest(unittest.TestCase):
    def test_bounds(self):
        names = [buien.kind_of(mm).label for mm in (0.1, 0.5, 1.9, 2, 5, 10, 40)]
        self.assertEqual(names, ["drizzle", "light", "light", "moderate", "heavy", "very heavy", "very heavy"])


class TripTest(unittest.TestCase):
    NOW = START.replace(minute=33)

    def plan(self, *mm, minutes=25, now=None):
        forecast = slots(*mm)
        return buien.describe_trip(buien.plan_trip(forecast, now or self.NOW, minutes), forecast)

    def test_dry_all_the_way(self):
        self.assertEqual(self.plan(*[0] * 24), "leave whenever you like, no rain in sight")

    def test_rain_on_the_way(self):
        self.assertEqual(self.plan(*[0] * 8, 1, *[0] * 15), "leave by 12:45 to stay dry for 25 min")

    def test_rain_now_that_stops(self):
        self.assertEqual(self.plan(1, 1, 1, *[0] * 21), "leave from 12:45 to stay dry for 25 min")

    def test_a_dry_spell_between_showers(self):
        self.assertEqual(self.plan(1, 1, *[0] * 7, *[1] * 15), "leave between 12:40 and 12:50 to stay dry for 25 min")

    def test_a_dry_spell_that_just_fits(self):
        self.assertEqual(self.plan(1, 1, *[0] * 5, *[1] * 17), "leave at 12:40 to stay dry for 25 min")

    def test_leave_right_now(self):
        self.assertEqual(self.plan(*[0] * 5, *[1] * 19, now=START), "leave now to stay dry for 25 min")

    def test_rain_in_the_slot_that_is_running(self):
        self.assertEqual(self.plan(1, *[0] * 23), "leave from 12:35 to stay dry for 25 min")

    def test_no_dry_spell_long_enough(self):
        self.assertEqual(self.plan(*[1, 0, 0] * 8), "no dry 25 min before 14:30")

    def test_longer_than_the_forecast(self):
        with self.assertRaisesRegex(buien.BuienError, "reaches only until 14:30, so a trip can take at most 117 minutes"):
            self.plan(*[0] * 24, minutes=120)

    def test_the_trip_is_drawn_on_the_axis(self):
        forecast = slots(1, 1, *[0] * 7, *[1] * 15)
        trip = buien.plan_trip(forecast, self.NOW, 25)
        window = buien.trip_window(forecast, trip)
        self.assertEqual(window, range(2, 9))
        line = buien.axis(forecast, 2, window)
        self.assertEqual(set(line[4:18]), {"━", "┯"})
        self.assertNotIn("━", line[:4] + line[18:])
        text = plain(buien.render(GENT, forecast, self.NOW, False, 100, trip))
        self.assertIn("leave between 12:40 and 12:50 to stay dry for 25 min", text)

    def test_a_trip_that_cannot_be_made_is_not_drawn_or_green(self):
        forecast = slots(*[1, 0, 0] * 8)
        trip = buien.plan_trip(forecast, self.NOW, 25)
        self.assertEqual(buien.trip_window(forecast, trip), range(0))
        text = buien.render(GENT, forecast, self.NOW, True, 100, trip)
        self.assertNotIn(f"38;5;{buien.TRIP_COLOR}m", text)
        self.assertIn("no dry 25 min before 14:30", plain(text))

    def test_minutes_are_required(self):
        for argv in (["--trip"], ["--trip", "gent"], ["--trip", "0"], ["--trip", "²"], ["--trip", "99999999999999"]):
            with self.assertRaisesRegex(buien.BuienError, "say how many minutes"):
                buien.parse_args(argv)


class ChartTest(unittest.TestCase):
    def render(self, forecast, width=100, color=False):
        now = START.replace(minute=33)
        return buien.render(GENT, forecast, now, color, width)

    def test_more_rain_draws_a_higher_bar(self):
        levels = [buien.bar_level(mm) for mm in (0, 0.1, 0.5, 2, 10, 50)]
        self.assertEqual(levels, sorted(levels))
        self.assertEqual(levels[0], 0)
        self.assertEqual(levels[1], 1)
        self.assertEqual(levels[-1], buien.ROWS * 8)

    def test_a_dry_forecast_draws_no_bars(self):
        text = self.render(slots(*[0] * 24))
        self.assertFalse(set(text) & set(buien.BLOCKS.strip()))
        self.assertIn("dry until at least 14:30", text)

    def test_a_dry_chart_says_so_in_its_middle_row(self):
        rows = buien.chart_rows(slots(*[0] * 24), 2, buien.Paint(False))
        self.assertEqual(rows[0], "")
        self.assertEqual(rows[1].strip(), "no rain in sight")
        self.assertEqual(len(rows[1]) - len(rows[1].lstrip()), (48 - len("no rain in sight")) // 2)

    def test_a_dry_chart_too_narrow_for_the_words_stays_empty(self):
        self.assertEqual(buien.chart_rows(slots(0, 0, 0), 2, buien.Paint(False)), ["", "", ""])

    def test_a_shower_draws_bars_in_its_own_columns(self):
        rows = buien.chart_rows(slots(0, 0, 10, 0), 2, buien.Paint(False))
        self.assertEqual([row.rstrip() for row in rows], ["    ██", "    ██", "    ██"])

    def test_axis_and_labels(self):
        forecast = slots(*[0] * 13)
        self.assertEqual(buien.axis(forecast, 1), "┬─────┬─────┬")
        self.assertEqual(buien.time_labels(forecast, 2), "now         13:00       13:30")
        self.assertEqual(buien.time_labels(forecast, 1), "now   13:00")

    def test_title_summary_and_legend(self):
        text = plain(self.render(slots(0, 0.1, 3, 0)))
        self.assertIn("Gent · 12:33", text)
        self.assertIn("drizzle █  moderate █", text)
        self.assertNotIn("light █", text)
        self.assertIn("dry until 12:35, then 10 min of light to moderate rain", text)
        self.assertIn("heaviest at 12:40: 3.0 mm per hour", text)

    def test_narrow_terminal_uses_one_column_per_slot(self):
        forecast = slots(*[1] * 36)
        wide = self.render(forecast, width=80).splitlines()
        narrow = self.render(forecast, width=60).splitlines()
        self.assertEqual(max(map(len, wide)), 2 + 72)
        self.assertLessEqual(max(map(len, narrow)), 60)

    def test_color_only_when_asked(self):
        forecast = slots(0, 1, 0)
        self.assertIn("\033[", self.render(forecast, color=True))
        self.assertNotIn("\033[", self.render(forecast, color=False))


def radar_answer(*mm):
    """Buienradar's answer with a slot every five minutes from 10:30 UTC."""
    return {
        "forecasts": [
            {"utcdatetime": f"2026-10-13T10:{30 + 5 * index}:00", "precipitation": value}
            for index, value in enumerate(mm)
        ]
    }


class ForecastTest(unittest.TestCase):
    def test_starts_at_the_slot_that_is_running(self):
        now = datetime(2026, 10, 13, 10, 37, tzinfo=timezone.utc)
        forecast = buien.parse_forecast(radar_answer(0, 0.5, 1.5, 0), now)
        self.assertEqual(forecast[0].time, datetime(2026, 10, 13, 10, 35, tzinfo=timezone.utc))
        self.assertEqual([slot.mm for slot in forecast], [0.5, 1.5, 0])

    def test_stale_forecast(self):
        now = datetime(2026, 10, 13, 12, 0, tzinfo=timezone.utc)
        with self.assertRaisesRegex(buien.BuienError, "out of date"):
            buien.parse_forecast(radar_answer(0, 0), now)

    def test_unexpected_answer(self):
        with self.assertRaisesRegex(buien.BuienError, "unexpected"):
            buien.parse_forecast({"forecasts": [{"precipitation": 1}]}, START)

    def test_outside_the_radar(self):
        with mock.patch.object(buien, "fetch_json", return_value=None):
            with self.assertRaisesRegex(buien.BuienError, "no radar for Madrid"):
                buien.fetch_forecast(buien.Place("Madrid", 40.4, -3.7), START)

    def test_a_connection_that_drops_halfway(self):
        response = mock.MagicMock()
        response.__enter__.return_value.read.side_effect = buien.http.client.IncompleteRead(b"{")
        with mock.patch.object(buien.urllib.request, "urlopen", return_value=response):
            with self.assertRaisesRegex(buien.BuienError, "no usable answer from graphdata.buienradar.nl"):
                buien.fetch_json("https://graphdata.buienradar.nl/x")

    def test_unreachable(self):
        error = urllib.error.URLError("no route")
        with mock.patch.object(buien.urllib.request, "urlopen", side_effect=error):
            with self.assertRaisesRegex(buien.BuienError, "unreachable"):
                buien.fetch_json("https://graphdata.buienradar.nl/x")


class CacheTest(unittest.TestCase):
    NOW = datetime(2026, 10, 13, 10, 32, tzinfo=timezone.utc)
    UNREACHABLE = buien.BuienError("graphdata.buienradar.nl is unreachable (no route)")

    def setUp(self):
        cache = tempfile.TemporaryDirectory()
        self.addCleanup(cache.cleanup)
        mock.patch.dict(os.environ, {"XDG_CACHE_HOME": cache.name}).start()
        self.fetch_json = mock.patch.object(buien, "fetch_json", return_value=radar_answer(0, 0, 0, 1, 0)).start()
        self.addCleanup(mock.patch.stopall)

    def fetch(self, minutes_later=0):
        return buien.fetch_forecast(GENT, self.NOW + timedelta(minutes=minutes_later))

    def test_a_fresh_forecast_is_reused(self):
        self.fetch()
        self.fetch(4)
        self.assertEqual(self.fetch_json.call_count, 1)

    def test_an_older_one_is_fetched_again(self):
        self.fetch()
        self.fetch(5)
        self.assertEqual(self.fetch_json.call_count, 2)

    def test_offline_shows_the_last_forecast(self):
        self.fetch()
        self.fetch_json.side_effect = self.UNREACHABLE
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            forecast = self.fetch(10)
        self.assertEqual([slot.mm for slot in forecast], [0, 1, 0])
        self.assertIn(f"unreachable (no route), showing the forecast from {buien.clock(self.NOW.astimezone())}", err.getvalue())

    def test_offline_without_a_forecast(self):
        self.fetch_json.side_effect = self.UNREACHABLE
        with self.assertRaisesRegex(buien.BuienError, "unreachable"):
            self.fetch()

    def test_offline_when_the_last_forecast_is_over(self):
        self.fetch()
        self.fetch_json.side_effect = self.UNREACHABLE
        with self.assertRaisesRegex(buien.BuienError, "unreachable"):
            self.fetch(60)

    def test_an_unreadable_cache_is_fetched_again(self):
        path = buien.cache_file(GENT)
        path.parent.mkdir(parents=True)
        path.write_text("{not json")
        self.assertEqual([slot.mm for slot in self.fetch()], [0, 0, 0, 1, 0])
        self.assertEqual(self.fetch_json.call_count, 1)

    def test_a_broken_answer_keeps_the_last_good_forecast(self):
        self.fetch()
        self.fetch_json.return_value = {"forecasts": [{"precipitation": 1}]}
        with self.assertRaisesRegex(buien.BuienError, "unexpected answer"):
            self.fetch(5)
        self.fetch_json.side_effect = self.UNREACHABLE
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual([slot.mm for slot in self.fetch(6)], [0, 0, 1, 0])

    def test_a_cache_without_a_time_zone_counts_as_none(self):
        path = buien.cache_file(GENT)
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps({"fetched": "2026-10-13T10:31:00", "data": radar_answer(0)}))
        self.fetch()
        self.assertEqual(self.fetch_json.call_count, 1)

    def test_forecasts_past_three_hours_old_are_removed(self):
        old = buien.cache_file(buien.Place("Brussel", 50.85, 4.35))
        old.parent.mkdir(parents=True)
        old.write_text("{}")
        hours_ago = (self.NOW - timedelta(hours=4)).timestamp()
        os.utime(old, (hours_ago, hours_ago))
        self.fetch()
        self.assertFalse(old.exists())
        self.assertTrue(buien.cache_file(GENT).exists())

    def test_no_radar_is_not_cached(self):
        self.fetch_json.return_value = None
        with self.assertRaisesRegex(buien.BuienError, "no radar"):
            self.fetch()
        self.assertFalse(buien.cache_file(GENT).exists())


class LookupTest(unittest.TestCase):
    def test_coordinates(self):
        self.assertEqual(buien.lookup("51.05,3.72"), buien.Place("51.05, 3.72", 51.05, 3.72))
        self.assertEqual(buien.lookup("-3.7, 40.4").lat, -3.7)

    def test_prefers_belgium_and_the_netherlands(self):
        results = {"results": [
            {"name": "Bergen", "country_code": "NO", "latitude": 60.39, "longitude": 5.32},
            {"name": "Bergen", "country_code": "BE", "latitude": 50.45, "longitude": 3.95},
        ]}
        with mock.patch.object(buien, "fetch_json", return_value=results):
            self.assertEqual(buien.lookup("bergen"), buien.Place("Bergen", 50.45, 3.95))

    def test_retries_with_hyphens(self):
        found = {"results": [{"name": "Sint-Niklaas", "country_code": "BE", "latitude": 51.17, "longitude": 4.14}]}
        with mock.patch.object(buien, "fetch_json", side_effect=[{}, found]) as fetch:
            self.assertEqual(buien.lookup("sint niklaas").name, "Sint-Niklaas")
        self.assertIn("name=sint-niklaas", fetch.call_args[0][0])

    def test_unknown_place(self):
        with mock.patch.object(buien, "fetch_json", return_value={}):
            with self.assertRaisesRegex(buien.BuienError, "no place found called 'xyzzy'"):
                buien.lookup("xyzzy")


def run_main(*argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = buien.main(list(argv))
    return code, out.getvalue(), err.getvalue()


class PlacesTest(unittest.TestCase):
    def setUp(self):
        config = tempfile.TemporaryDirectory()
        self.addCleanup(config.cleanup)
        self.places_file = os.path.join(config.name, "buien", "places.json")
        self.lookup = mock.patch.object(
            buien, "lookup", side_effect=lambda text, choose=False: buien.Place(text.title(), 51.05, 3.72)
        ).start()
        mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": config.name}).start()
        mock.patch.object(buien, "fetch_forecast", return_value=slots(0, 0)).start()
        self.addCleanup(mock.patch.stopall)

    def test_home_is_remembered(self):
        code, _, err = run_main("--home", "gent")
        self.assertEqual(code, 0)
        self.assertIn("Gent is saved as home, from now on plain buien is enough", err)
        code, out, _ = run_main()
        self.assertEqual(code, 0)
        self.assertIn("Gent · ", plain(out))

    def test_another_place_leaves_home_alone(self):
        run_main("--home", "gent")
        run_main("brugge")
        self.assertEqual(buien.load_places()["home"].name, "Gent")

    def test_home_needs_a_place(self):
        code, _, err = run_main("--home")
        self.assertEqual(code, 1)
        self.assertIn("buien --home gent", err)

    def test_a_place_saved_under_its_own_name(self):
        code, out, err = run_main("--save", "work", "brussel")
        self.assertEqual(code, 0)
        self.assertIn("Brussel is saved as work, from now on buien work is enough", err)
        self.assertIn("Brussel · ", plain(out))
        self.lookup.reset_mock()
        code, out, _ = run_main("work")
        self.assertEqual(code, 0)
        self.assertIn("Brussel · ", plain(out))
        self.lookup.assert_not_called()

    def test_saved_names_ignore_case_and_may_be_several_words(self):
        run_main("--save", "Grandma Lisa", "sint", "niklaas")
        code, out, _ = run_main("grandma", "lisa")
        self.assertEqual(code, 0)
        self.assertIn("Sint Niklaas · ", plain(out))

    def test_save_needs_a_name_and_a_place(self):
        code, _, err = run_main("--save", "work")
        self.assertEqual(code, 1)
        self.assertIn("buien --save work brussel", err)
        self.assertFalse(os.path.exists(self.places_file))

    def test_every_place_is_kept_and_saving_again_replaces(self):
        run_main("--home", "gent")
        run_main("--save", "work", "brussel")
        run_main("--save", "work", "leuven")
        places = buien.load_places()
        self.assertEqual(sorted(places), ["home", "work"])
        self.assertEqual(places["work"].name, "Leuven")

    def test_an_unsaved_name_is_looked_up(self):
        run_main("--save", "work", "brussel")
        code, out, _ = run_main("brugge")
        self.assertEqual(code, 0)
        self.assertIn("Brugge · ", plain(out))

    def test_places_lists_home_first(self):
        run_main("--save", "work", "brussel")
        run_main("--save", "gym", "leuven")
        run_main("--home", "gent")
        code, out, _ = run_main("--places")
        self.assertEqual(code, 0)
        self.assertEqual(out.splitlines(), [
            "home  Gent (51.05, 3.72)",
            "gym   Leuven (51.05, 3.72)",
            "work  Brussel (51.05, 3.72)",
        ])

    def test_places_when_nothing_is_saved(self):
        code, out, _ = run_main("--places")
        self.assertEqual(code, 0)
        self.assertIn("no saved places yet", out)

    def test_forget(self):
        run_main("--home", "gent")
        run_main("--save", "work", "brussel")
        code, _, err = run_main("--forget", "Work")
        self.assertEqual(code, 0)
        self.assertIn("forgot work", err)
        self.assertEqual(sorted(buien.load_places()), ["home"])

    def test_forget_an_unknown_place(self):
        code, _, err = run_main("--forget", "work")
        self.assertEqual(code, 1)
        self.assertIn("no saved place called 'work'", err)
        code, _, err = run_main("--forget")
        self.assertEqual(code, 1)
        self.assertIn("buien --forget work", err)

    def test_first_run_outside_a_terminal(self):
        with mock.patch.object(buien.sys.stdin, "isatty", return_value=False):
            code, _, err = run_main()
        self.assertEqual(code, 1)
        self.assertIn("no home saved yet", err)

    def test_first_run_asks_for_home(self):
        with mock.patch.object(buien.sys.stdin, "isatty", return_value=True), \
                mock.patch("builtins.input", return_value="leuven") as ask:
            code, out, _ = run_main()
        self.assertEqual(code, 0)
        ask.assert_called_once()
        self.assertIn("Leuven · ", plain(out))
        self.assertEqual(buien.load_places()["home"], buien.Place("Leuven", 51.05, 3.72))

    def test_a_failed_save_keeps_the_places_file_whole(self):
        run_main("--home", "gent")
        with open(self.places_file) as places:
            before = places.read()
        with mock.patch.object(buien.os, "replace", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                run_main("--save", "work", "brussel")
        with open(self.places_file) as places:
            self.assertEqual(places.read(), before)
        self.assertEqual(os.listdir(os.path.dirname(self.places_file)), ["places.json"])

    def test_unreadable_places(self):
        os.makedirs(os.path.dirname(self.places_file))
        with open(self.places_file, "w") as file:
            file.write("{broken")
        code, _, err = run_main()
        self.assertEqual(code, 1)
        self.assertIn("unreadable", err)


BERGEN = {"results": [
    {"name": "Bergen", "country_code": "NO", "country": "Noorwegen", "admin1": "Vestland",
     "admin2": "Bergen", "latitude": 60.39, "longitude": 5.32},
    {"name": "Bergen", "country_code": "BE", "country": "België", "admin1": "Waals Gewest",
     "admin2": "Henegouwen", "latitude": 50.45, "longitude": 3.95},
    {"name": "Bergen", "country_code": "NL", "country": "Nederland", "admin1": "Noord-Holland",
     "admin2": "Bergen (NH.)", "latitude": 52.67, "longitude": 4.70},
]}


class CompletionTest(unittest.TestCase):
    def setUp(self):
        config = tempfile.TemporaryDirectory()
        self.addCleanup(config.cleanup)
        mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": config.name}).start()
        self.addCleanup(mock.patch.stopall)

    def test_every_flag_in_the_help_is_completed_and_understood(self):
        documented = set(re.findall(r"--[a-z-]+", buien.__doc__))
        completed = {flag.long for flag in buien.FLAGS}
        self.assertEqual(completed - {"--help"}, documented)
        for flag in buien.FLAGS:
            for name in filter(None, (flag.short, flag.long)):
                buien.parse_args([name, "25"] if flag.value else [name])

    def test_place_names_for_completion(self):
        code, out, _ = run_main("--places", "--short")
        self.assertEqual((code, out), (0, ""))
        buien.write_places({"work": GENT, "home": GENT, "sint niklaas": GENT})
        code, out, _ = run_main("--places", "--short")
        self.assertEqual(out, "home\nsint niklaas\nwork\n")

    def test_an_unknown_shell(self):
        code, _, err = run_main("--completions", "tcsh")
        self.assertEqual(code, 1)
        self.assertIn("say which shell to complete for: bash, fish, zsh", err)

    @unittest.skipUnless(shutil.which("bash"), "needs bash")
    def test_bash_completes_options_shells_and_saved_places(self):
        script = buien.completion_script("bash")
        probe = (
            'buien() { printf "home\\nwork\\nsint niklaas\\n"; }\n'
            f"{script}\n"
            'for words in "buien w" "buien s" "buien --sh" "buien --completions z"; do\n'
            '  read -ra COMP_WORDS <<< "$words"; COMP_CWORD=$(( ${#COMP_WORDS[@]} - 1 ))\n'
            '  _buien; (IFS=,; echo "${COMPREPLY[*]}")\n'
            "done\n"
        )
        out = subprocess.run(["bash", "-c", probe], capture_output=True, text=True, check=True).stdout
        self.assertEqual(out.splitlines(), ["work", "sint niklaas", "--short", "zsh"])

    def test_scripts_are_valid_for_their_shell(self):
        for shell in buien.SHELLS:
            with self.subTest(shell=shell):
                if not shutil.which(shell):
                    self.skipTest(f"needs {shell}")
                result = subprocess.run([shell, "-n"], input=buien.completion_script(shell), capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)


class SearchTest(unittest.TestCase):
    def setUp(self):
        config = tempfile.TemporaryDirectory()
        self.addCleanup(config.cleanup)
        mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": config.name}).start()
        self.fetch_json = mock.patch.object(buien, "fetch_json", return_value=BERGEN).start()
        self.fetch_forecast = mock.patch.object(buien, "fetch_forecast", return_value=slots(0, 0)).start()
        self.addCleanup(mock.patch.stopall)

    def search(self, *argv, answer=None):
        is_terminal = answer is not None
        with mock.patch.object(buien.sys.stdin, "isatty", return_value=is_terminal), \
                mock.patch("builtins.input", return_value=answer or ""):
            return run_main("--search", *argv)

    def test_lists_every_match_belgian_and_dutch_first(self):
        code, out, _ = self.search("bergen")
        self.assertEqual(code, 0)
        self.assertEqual(out.splitlines(), [
            "  1  Bergen, Henegouwen     België",
            "  2  Bergen, Noord-Holland  Nederland",
            "  3  Bergen, Vestland       Noorwegen",
        ])
        self.fetch_forecast.assert_not_called()

    def test_shows_the_one_you_pick(self):
        code, out, _ = self.search("bergen", answer="2")
        self.assertEqual(code, 0)
        self.assertIn("Bergen, Noord-Holland · ", plain(out))
        self.assertEqual(self.fetch_forecast.call_args[0][0], buien.Place("Bergen, Noord-Holland", 52.67, 4.70))

    def test_enter_stops_without_a_forecast(self):
        code, _, _ = self.search("bergen", answer="")
        self.assertEqual(code, 0)
        self.fetch_forecast.assert_not_called()

    def test_a_number_out_of_range(self):
        code, _, err = self.search("bergen", answer="7")
        self.assertEqual(code, 1)
        self.assertIn("pick a number from 1 to 3", err)

    def test_saves_the_one_you_pick(self):
        code, _, err = self.search("--save", "beach", "bergen", answer="2")
        self.assertEqual(code, 0)
        self.assertIn("Bergen, Noord-Holland is saved as beach", err)
        self.assertEqual(buien.load_places()["beach"].lat, 52.67)

    def test_saves_nothing_without_a_pick(self):
        code, _, _ = self.search("--home", "bergen", answer="")
        self.assertEqual(code, 0)
        self.assertEqual(buien.load_places(), {})

    def test_searches_past_a_saved_name(self):
        buien.write_places({"bergen": buien.Place("Gent", 51.05, 3.72)})
        code, out, _ = self.search("bergen")
        self.assertEqual(code, 0)
        self.assertIn("Bergen, Henegouwen", out)

    def test_search_needs_a_name(self):
        code, _, err = self.search()
        self.assertEqual(code, 1)
        self.assertIn("buien --search bergen", err)

    def test_plain_lookup_takes_the_first_match_with_its_province(self):
        self.assertEqual(buien.lookup("bergen"), buien.Place("Bergen, Henegouwen", 50.45, 3.95))

    def test_no_province_when_it_is_the_place_itself(self):
        result = {"name": "Antwerpen", "country_code": "BE", "admin1": "Vlaams Gewest",
                  "admin2": "Antwerpen", "latitude": 51.22, "longitude": 4.40}
        self.assertEqual(buien.to_place(result).name, "Antwerpen")
        self.assertEqual(buien.to_place({**result, "admin2": None, "admin1": None}).name, "Antwerpen")


class CommandTest(unittest.TestCase):
    def test_place_of_several_words(self):
        self.assertEqual(buien.parse_args(["sint", "niklaas"]).words, ["sint", "niklaas"])

    def test_negative_coordinates_are_not_an_option(self):
        self.assertEqual(buien.parse_args(["-3.7,40.4"]).words, ["-3.7,40.4"])

    def test_unknown_option(self):
        code, _, err = run_main("--foo")
        self.assertEqual(code, 1)
        self.assertIn("buien: unknown option --foo", err)

    def test_help(self):
        code, out, _ = run_main("-h")
        self.assertEqual(code, 0)
        self.assertIn("buien gent", out)

    def test_version(self):
        code, out, _ = run_main("--version")
        self.assertEqual(code, 0)
        self.assertEqual(out, f"buien {buien.__version__}\n")

    def test_the_package_has_the_same_version(self):
        with open(os.path.join(HERE, "pyproject.toml")) as pyproject:
            version = re.search(r'^version = "(.+)"$', pyproject.read(), re.MULTILINE)[1]
        self.assertEqual(version, buien.__version__)

    def test_requests_name_buien_and_its_version(self):
        response = mock.MagicMock()
        response.__enter__.return_value = io.BytesIO(b"{}")
        with mock.patch.object(buien.urllib.request, "urlopen", return_value=response) as urlopen:
            buien.fetch_json("https://graphdata.buienradar.nl/x")
        agent = urlopen.call_args.args[0].get_header("User-agent")
        self.assertEqual(agent, f"buien/{buien.__version__} (+https://github.com/PieterLuypaert/buien)")

    def run_with_forecast(self, *argv):
        with mock.patch.object(buien, "lookup", return_value=GENT), \
                mock.patch.object(buien, "fetch_forecast", return_value=slots(0, 1.5, 0)):
            return run_main("gent", *argv)

    def test_short_prints_only_the_summary(self):
        code, out, _ = self.run_with_forecast("--short")
        self.assertEqual(code, 0)
        self.assertEqual(out, "dry until 12:35, then 5 min of light rain\n")

    def test_json(self):
        code, out, _ = self.run_with_forecast("--json")
        self.assertEqual(code, 0)
        data = json.loads(out)
        self.assertEqual(data["place"], "Gent")
        self.assertEqual(data["summary"], "dry until 12:35, then 5 min of light rain")
        self.assertEqual([slot["mm_per_hour"] for slot in data["forecast"]], [0, 1.5, 0])
        self.assertEqual(data["forecast"][1]["time"], START.replace(minute=35).isoformat(timespec="minutes"))

    def run_trip(self, forecast, *argv):
        class Frozen(datetime):
            @classmethod
            def now(cls, tz=None):
                return START.replace(minute=33)

        with mock.patch.object(buien, "lookup", return_value=GENT), \
                mock.patch.object(buien, "fetch_forecast", return_value=forecast), \
                mock.patch.object(buien, "datetime", Frozen):
            return run_main("gent", "--trip", "25", *argv)

    def test_trip_exits_0_when_you_can_leave_now(self):
        code, out, _ = self.run_trip(slots(*[0] * 24), "--short")
        self.assertEqual((code, out), (0, "leave whenever you like, no rain in sight\n"))

    def test_trip_exits_2_when_you_have_to_wait(self):
        code, out, _ = self.run_trip(slots(1, 1, 1, *[0] * 21), "--short")
        self.assertEqual((code, out), (2, "leave from 12:45 to stay dry for 25 min\n"))

    def test_trip_exits_0_without_short_so_a_prompt_stays_calm(self):
        code, _, _ = self.run_trip(slots(1, 1, 1, *[0] * 21), "--json")
        self.assertEqual(code, 0)

    def test_trip_in_json(self):
        _, out, _ = self.run_trip(slots(1, 1, *[0] * 7, *[1] * 15), "--json")
        trip = json.loads(out)["trip"]
        self.assertEqual(trip["minutes"], 25)
        self.assertFalse(trip["leave_now"])
        self.assertEqual(trip["earliest"], START.replace(minute=40).isoformat(timespec="minutes"))
        self.assertEqual(trip["latest"], START.replace(minute=50).isoformat(timespec="minutes"))
        self.assertEqual(trip["summary"], "leave between 12:40 and 12:50 to stay dry for 25 min")

    def test_color_follows_the_flags_then_the_environment_then_the_terminal(self):
        def color(*argv, env=None, terminal=False):
            with mock.patch.dict(os.environ, env or {}), \
                    mock.patch.object(buien.sys.stdout, "isatty", return_value=terminal):
                return buien.use_color(buien.parse_args(list(argv)))

        with mock.patch.dict(os.environ):
            os.environ.pop("NO_COLOR", None)
            os.environ.pop("FORCE_COLOR", None)
            self.assertTrue(color(terminal=True))
            self.assertFalse(color())
            self.assertFalse(color(env={"NO_COLOR": "1"}, terminal=True))
            self.assertTrue(color(env={"FORCE_COLOR": "1"}))
            self.assertTrue(color("--color", env={"NO_COLOR": "1"}))
            self.assertFalse(color("--no-color", terminal=True))

    def test_shows_the_chart(self):
        with mock.patch.object(buien, "lookup", return_value=GENT), \
                mock.patch.object(buien, "fetch_forecast", return_value=slots(0, 1, 0)):
            code, out, _ = run_main("gent")
        self.assertEqual(code, 0)
        self.assertIn("dry until 12:35, then 5 min of light rain", out)


if __name__ == "__main__":
    unittest.main()
