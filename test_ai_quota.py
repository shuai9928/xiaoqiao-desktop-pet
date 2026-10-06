"""Synthetic quota fixtures only; no user files, network, Tk or models."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from ai_quota import CODEX_SOURCE, quota_accounts, quota_view, read_codex_quota


NOW = 1791081600.0


def codex(age=30, used=(0, 46), resets=None):
    stamp = (NOW-age)*1000
    resets = resets if resets is not None else (NOW+1200, NOW+86400)
    return {"provider": "codex", "t": stamp, "source": "Untrusted file label",
            "cycles": [{"label": "5 小时", "minutes": 300, "used": used[0], "reset": resets[0]},
                       {"label": "7 天", "minutes": 10080, "used": used[1], "reset": resets[1]}]}


class ReaderTests(unittest.TestCase):
    def read(self, raw, bom=False):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/"mock-quota.json"
            path.write_text(json.dumps(raw), encoding="utf-8-sig" if bom else "utf-8")
            return read_codex_quota(path)

    def test_whitelist_removes_credentials_and_untrusted_source(self):
        raw = codex()
        raw.update(account_id="synthetic-account", api_key="synthetic-secret",
                   status="current", arbitrary={"secret": "synthetic"})
        raw["cycles"][0].update(account_id="fake", secret="fake")
        raw["cycles"][0]["label"] = "untrusted content"
        result = self.read(raw, bom=True)
        self.assertEqual(set(result), {"provider", "t", "cycles", "source"})
        self.assertEqual(result["source"], CODEX_SOURCE)
        self.assertEqual(result["t"], (NOW-30)*1000)
        self.assertEqual(result["cycles"][0]["label"], "5 小时")
        for row in result["cycles"]:
            self.assertEqual(set(row), {"label", "used", "minutes", "reset"})
        self.assertNotIn("synthetic", str(result))

    def test_invalid_used_becomes_unknown_instead_of_zero_or_clamped_full(self):
        for value in (True, False, float("nan"), float("inf"), -1, 101, "42", None):
            with self.subTest(value=value):
                result = self.read(codex(used=(value, 46)))
                self.assertIsNone(result["cycles"][0]["used"])
                view = quota_view({"now": NOW, "codex_quota": result}, "codex")
                self.assertIsNone(view["cycles"][0]["remaining"])
                self.assertEqual(view["cycles"][1]["remaining"], 54)

    def test_valid_zero_and_hundred_are_real_values(self):
        result = self.read(codex(used=(0, 100)))
        view = quota_view({"now": NOW, "codex_quota": result})
        self.assertEqual([row["remaining"] for row in view["cycles"]], [100, 0])
        self.assertEqual(view["status"], "current")

    def test_missing_and_duplicate_cycles_stay_unknown(self):
        raw = codex()
        raw["cycles"] = raw["cycles"][:1]
        result = self.read(raw)
        self.assertIsNone(result["cycles"][1]["used"])
        self.assertIsNone(result["cycles"][1]["reset"])
        raw["cycles"].append(dict(raw["cycles"][0], used=85))
        self.assertIsNone(self.read(raw)["cycles"][0]["used"])

    def test_reset_must_be_finite_seconds_after_sample(self):
        for reset in (True, 0, float("inf"), float("nan"), "1791082800", NOW-30, NOW-60):
            with self.subTest(reset=reset):
                result = self.read(codex(resets=(reset, NOW+86400)))
                self.assertIsNone(result["cycles"][0]["reset"])
                self.assertEqual(result["cycles"][1]["reset"], NOW+86400)

    def test_bad_sample_time_invalidates_reset_without_filling_usage(self):
        for stamp in (None, True, 0, -1, float("inf"), float("nan"), "1791081600000"):
            with self.subTest(stamp=stamp):
                raw = codex()
                raw["t"] = stamp
                result = self.read(raw)
                self.assertIsNone(result["t"])
                self.assertIsNone(result["cycles"][0]["reset"])
                self.assertEqual(result["cycles"][1]["used"], 46)

    def test_finite_but_unformatable_sample_and_reset_times_are_unknown(self):
        for value in (1e100, 253402300800.0):  # Finite overflow / UTC year 10000.
            with self.subTest(seconds=value):
                raw = codex()
                raw["t"] = value*1000
                result = self.read(raw)
                self.assertIsNone(result["t"])
                self.assertEqual(result["cycles"][1]["used"], 46)
                view = quota_view({"now": NOW, "codex_quota": result})
                self.assertEqual(view["status"], "unknown")
                self.assertTrue(view["stale"])
                self.assertEqual(view["cycles"][1]["remaining"], 54)
                result = self.read(codex(resets=(value, NOW+86400)))
                self.assertIsNone(result["cycles"][0]["reset"])
                self.assertEqual(result["cycles"][1]["reset"], NOW+86400)

    def test_platform_localtime_failure_is_rejected_before_rendering(self):
        with patch("ai_quota.time.localtime", side_effect=OSError("unsupported clock")):
            result = self.read(codex())
        self.assertIsNone(result["t"])
        self.assertIsNone(result["cycles"][0]["reset"])
        self.assertEqual(result["cycles"][0]["used"], 0)

    def test_other_provider_and_invalid_roots_are_rejected(self):
        for raw in ({"provider": "claude"}, {"provider": "CODEX"}, [], None, 5):
            with self.subTest(raw=raw):
                self.assertIsNone(self.read(raw))

    def test_missing_malformed_and_oversized_files_do_not_raise(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/"mock-quota.json"
            self.assertIsNone(read_codex_quota(path))
            path.write_text("{broken", encoding="utf-8")
            self.assertIsNone(read_codex_quota(path))
            path.write_text(" "*65537, encoding="utf-8")
            self.assertIsNone(read_codex_quota(path))
            self.assertIsNone(read_codex_quota(directory))


class ViewTests(unittest.TestCase):
    def test_quota_selectors_do_not_create_sessions_or_mutate_ui(self):
        ui = {"now": NOW, "sessions": []}
        self.assertEqual(quota_accounts(ui), [("codex", "Codex"), ("claude", "Claude"), ("zcode", "ZCode")])
        quota_accounts(ui).clear()
        self.assertEqual(len(quota_accounts(ui)), 3)
        self.assertEqual(ui, {"now": NOW, "sessions": []})

    def test_explicit_and_pinned_quota_provider_override_selected_workflow(self):
        ui = {"now": NOW, "sel_key": "zcode", "quota_provider": "codex", "codex_quota": codex()}
        self.assertEqual(quota_view(ui)["provider"], "codex")
        self.assertEqual(quota_view(ui, "claude")["provider"], "claude")
        self.assertEqual(ui["sel_key"], "zcode")

    def test_source_aliases_preserve_account_ownership(self):
        for source, expected in (("mac", "codex"), ("mac-codex", "codex"), ("wslcodex", "codex"),
                                 ("claude", "claude"), ("macclaude", "claude"),
                                 ("mac-claude", "claude"), ("zcode", "zcode")):
            with self.subTest(source=source):
                self.assertEqual(quota_view({"now": NOW, "sel_key": source,
                                            "codex_quota": codex()})["provider"], expected)

    def test_without_selection_existing_codex_precedes_claude(self):
        ui = {"now": NOW, "codex_quota": codex(), "quota": {"fh": 32, "t": NOW*1000}}
        self.assertEqual(quota_view(ui)["provider"], "codex")
        ui["codex_quota"] = None
        self.assertEqual(quota_view(ui)["provider"], "claude")

    def test_age_and_reset_boundaries_do_not_invent_recovered_quota(self):
        for age, stale in ((3600, False), (3600.01, True)):
            with self.subTest(age=age):
                view = quota_view({"now": NOW, "codex_quota": codex(age=age)})
                self.assertEqual(view["stale"], stale)
        view = quota_view({"now": NOW, "codex_quota": codex(used=(75, 46), resets=(NOW, NOW+86400))})
        self.assertEqual(view["status"], "stale")
        self.assertEqual(view["cycles"][0]["remaining"], 25)
        self.assertTrue(view["cycles"][0]["stale"])
        self.assertFalse(view["cycles"][1]["stale"])

    def test_missing_or_future_time_is_never_fresh(self):
        for stamp in (None, (NOW+60)*1000):
            with self.subTest(stamp=stamp):
                raw = codex()
                raw["t"] = stamp
                view = quota_view({"now": NOW, "codex_quota": raw})
                self.assertIsNone(view["age"])
                self.assertEqual(view["status"], "unknown")
                self.assertTrue(view["stale"])

    def test_claude_extreme_time_preserves_used_without_formatting_a_fake_date(self):
        for stamp in (1e100, (NOW+60)*1000):
            with self.subTest(stamp=stamp):
                view = quota_view({"now": NOW, "quota": {"fh": 32, "sd": 58,
                                                        "t": stamp, "reset_est": 1e100}}, "claude")
                self.assertEqual(view["status"], "unknown")
                self.assertTrue(view["stale"])
                self.assertEqual(view["cycles"][0]["remaining"], 68)
                self.assertIsNone(view["cycles"][0]["reset"])
                self.assertFalse(view["cycles"][0]["estimated"])

    def test_unformatable_ui_now_uses_the_real_clock_without_poisoning_age(self):
        with patch("ai_quota.time.time", return_value=NOW):
            view = quota_view({"now": 1e100, "codex_quota": codex()})
        self.assertEqual(view["age"], 30)
        self.assertEqual(view["status"], "current")

    def test_partial_and_missing_samples_are_distinct_from_zero(self):
        raw = codex()
        raw["cycles"] = raw["cycles"][:1]
        view = quota_view({"now": NOW, "codex_quota": raw})
        self.assertEqual(view["status"], "partial")
        self.assertEqual(view["cycles"][0]["remaining"], 100)
        self.assertIsNone(view["cycles"][1]["remaining"])
        for provider in ("codex", "claude", "zcode"):
            empty = quota_view({"now": NOW}, provider)
            self.assertEqual(empty["status"], "unknown")
            self.assertTrue(all(row["used"] is None and row["remaining"] is None for row in empty["cycles"]))

    def test_read_error_retains_last_values_without_claiming_current(self):
        view = quota_view({"now": NOW, "codex_quota": codex(), "codex_quota_error": True})
        self.assertEqual(view["status"], "read_error")
        self.assertEqual(view["cycles"][1]["remaining"], 54)
        self.assertTrue(all(row["stale"] for row in view["cycles"]))
        missing = quota_view({"now": NOW, "codex_quota_error": True})
        self.assertEqual(missing["status"], "read_error")
        self.assertIsNone(missing["cycles"][0]["remaining"])

    def test_claude_only_five_hour_reset_is_estimated(self):
        view = quota_view({"now": NOW, "quota": {"fh": 32, "sd": 58, "t": (NOW-60)*1000,
                                                "reset_est": NOW+1200}, "quota_age": 60}, "claude")
        self.assertEqual([row["remaining"] for row in view["cycles"]], [68, 42])
        self.assertTrue(view["cycles"][0]["estimated"])
        self.assertFalse(view["cycles"][1]["estimated"])
        self.assertIsNone(view["cycles"][1]["reset"])
        self.assertEqual(view["note"], "本机用量样本")

    def test_claude_supplied_age_cannot_hide_old_or_missing_sample_time(self):
        for stamp, supplied in (((NOW-7200)*1000, 0), (None, 0), (NOW*1000, 7200)):
            with self.subTest(stamp=stamp, supplied=supplied):
                view = quota_view({"now": NOW, "quota": {"fh": 32, "t": stamp},
                                   "quota_age": supplied}, "claude")
                self.assertTrue(view["stale"])
                self.assertNotIn(view["status"], ("current", "partial"))

    def test_claude_invalid_values_and_past_reset_do_not_show_false_quota(self):
        view = quota_view({"now": NOW, "quota": {"fh": -5, "sd": True, "t": (NOW-60)*1000,
                                                "reset_est": NOW}}, "claude")
        self.assertEqual(view["status"], "unknown")
        self.assertTrue(view["stale"])
        self.assertTrue(all(row["remaining"] is None for row in view["cycles"]))

    def test_codex_note_is_snapshot_not_automatic_sync_claim(self):
        view = quota_view({"now": NOW, "codex_quota": codex()})
        self.assertEqual(view["note"], "用量快照 · 自动同步尚未接入")
        self.assertTrue(all(not row["estimated"] for row in view["cycles"]))
        self.assertEqual(quota_view({"now": NOW}, "zcode")["note"], "额度尚未接入")


if __name__ == "__main__":
    unittest.main()
