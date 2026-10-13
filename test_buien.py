"""Tests for buien. Run with: python3 -m unittest"""
import contextlib
import importlib.machinery
import importlib.util
import io
import json
import os
import sys
import tempfile
import unittest
import urllib.error
from datetime import datetime, timezone
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
_loader = importlib.machinery.SourceFileLoader("buien", os.path.join(HERE, "buien"))
buien = importlib.util.module_from_spec(importlib.util.spec_from_loader("buien", _loader))
sys.modules["buien"] = buien
_loader.exec_module(buien)

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


class ForecastTest(unittest.TestCase):
    def data(self, *mm):
        return {
            "forecasts": [
                {"utcdatetime": f"2026-10-13T10:{30 + 5 * index}:00", "precipitation": value}
                for index, value in enumerate(mm)
            ]
        }

    def test_starts_at_the_slot_that_is_running(self):
        now = datetime(2026, 10, 13, 10, 37, tzinfo=timezone.utc)
        forecast = buien.parse_forecast(self.data(0, 0.5, 1.5, 0), now)
        self.assertEqual(forecast[0].time, datetime(2026, 10, 13, 10, 35, tzinfo=timezone.utc))
        self.assertEqual([slot.mm for slot in forecast], [0.5, 1.5, 0])

    def test_stale_forecast(self):
        now = datetime(2026, 10, 13, 12, 0, tzinfo=timezone.utc)
        with self.assertRaisesRegex(buien.BuienError, "out of date"):
            buien.parse_forecast(self.data(0, 0), now)

    def test_unexpected_answer(self):
        with self.assertRaisesRegex(buien.BuienError, "unexpected"):
            buien.parse_forecast({"forecasts": [{"precipitation": 1}]}, START)

    def test_outside_the_radar(self):
        with mock.patch.object(buien, "fetch_json", return_value=None):
            with self.assertRaisesRegex(buien.BuienError, "no radar for Madrid"):
                buien.fetch_forecast(buien.Place("Madrid", 40.4, -3.7), START)

    def test_unreachable(self):
        error = urllib.error.URLError("no route")
        with mock.patch.object(buien.urllib.request, "urlopen", side_effect=error):
            with self.assertRaisesRegex(buien.BuienError, "unreachable"):
                buien.fetch_json("https://graphdata.buienradar.nl/x")


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


class HomeTest(unittest.TestCase):
    def setUp(self):
        config = tempfile.TemporaryDirectory()
        self.addCleanup(config.cleanup)
        self.home_file = os.path.join(config.name, "buien", "home.json")
        patches = [
            mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": config.name}),
            mock.patch.object(buien, "lookup", side_effect=lambda text: buien.Place(text.title(), 51.05, 3.72)),
            mock.patch.object(buien, "fetch_forecast", return_value=slots(0, 0)),
        ]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)

    def test_home_is_remembered(self):
        code, _, err = run_main("--home", "gent")
        self.assertEqual(code, 0)
        self.assertIn("Gent is now home", err)
        code, out, _ = run_main()
        self.assertEqual(code, 0)
        self.assertIn("Gent · ", plain(out))

    def test_another_place_leaves_home_alone(self):
        run_main("--home", "gent")
        run_main("brugge")
        self.assertEqual(buien.load_home().name, "Gent")

    def test_home_needs_a_place(self):
        code, _, err = run_main("--home")
        self.assertEqual(code, 1)
        self.assertIn("buien --home gent", err)

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
        self.assertEqual(buien.load_home(), buien.Place("Leuven", 51.05, 3.72))

    def test_unreadable_home(self):
        os.makedirs(os.path.dirname(self.home_file))
        with open(self.home_file, "w") as file:
            file.write("{kapot")
        code, _, err = run_main()
        self.assertEqual(code, 1)
        self.assertIn("unreadable", err)


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

    def test_shows_the_chart(self):
        with mock.patch.object(buien, "lookup", return_value=GENT), \
                mock.patch.object(buien, "fetch_forecast", return_value=slots(0, 1, 0)):
            code, out, _ = run_main("gent")
        self.assertEqual(code, 0)
        self.assertIn("dry until 12:35, then 5 min of light rain", out)


if __name__ == "__main__":
    unittest.main()
