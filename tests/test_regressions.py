"""用户数据与播放流程中已发现问题的回归测试。"""
from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

import harpguide.app as app_module
import harpguide.storage as storage
from harpguide.app import AppController
from harpguide.calibration import CalibrationData, KeyGeom
from harpguide.config import Settings
from harpguide.editor import EditorWindow
from harpguide.hintbar import HOTKEY_HINTS
from harpguide.hotkeys import HOTKEY_DEFS, HOTKEY_LABELS
from harpguide.keywatch import KeyWatcher
from harpguide.models import LyricLine, Note, NoteType, Score, load_scores
from harpguide.playback import PlaybackEngine


def sample_score(score_id: str = "song", name: str = "测试曲") -> Score:
    return Score(
        id=score_id, name=name, bpm=120,
        notes=[Note("Z", NoteType.TAP, 1.0, 0.0),
               Note("X", NoteType.TAP, 1.0, 1.0)],
    )


class DataSafetyTests(unittest.TestCase):
    def test_invalid_calibration_profile_does_not_hide_valid_profile(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "calibration.json"
            valid_keys = [{"x": 50 + i * 70, "y": 50, "size": 64} for i in range(8)]
            invalid_keys = [dict(key) for key in valid_keys]
            invalid_keys[0]["size"] = float("nan")
            import json
            path.write_text(json.dumps({"version": 1, "profiles": {
                "broken": {"keys": invalid_keys},
                "valid": {"keys": valid_keys},
            }}), encoding="utf-8")
            calibration = CalibrationData.load(path)
            self.assertNotIn("broken", calibration.profiles)
            self.assertEqual(len(calibration.profiles["valid"]), 8)

    def test_atomic_save_keeps_old_score_if_replace_fails(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "song.json"
            sample_score(name="原曲").save(path)
            original = path.read_bytes()
            with patch.object(storage.os, "replace", side_effect=OSError("模拟写入失败")):
                with self.assertRaises(OSError):
                    sample_score(name="修改后").save(path)
            self.assertEqual(path.read_bytes(), original)
            self.assertEqual(list(Path(folder).glob("*.tmp")), [])

    def test_invalid_bpm_is_skipped_before_playback(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "bad.json"
            path.write_text('{"id":"bad","bpm":0,"notes":[]}', encoding="utf-8")
            self.assertEqual(load_scores(folder), [])

    def test_malformed_settings_use_safe_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "settings.json"
            path.write_text(
                '{"_path":"elsewhere","speed_multiplier":"wrong",'
                '"opacity":99,"window_w":null,"risk_accepted":"yes",'
                '"lookahead_ms":0}', encoding="utf-8")
            settings = Settings.load(path)
            self.assertEqual(settings._path, path)
            self.assertEqual(settings.speed_multiplier, 1.0)
            self.assertEqual(settings.opacity, 1.0)
            self.assertEqual(settings.window_w, 600)
            self.assertFalse(settings.risk_accepted)
            self.assertEqual(settings.lookahead_ms, 600)

    def test_rename_never_overwrites_another_song(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            songs = root / "scores"
            songs.mkdir()
            old = sample_score("old", "原曲")
            other = sample_score("target", "target")
            old.save(songs / "old.json")
            other.save(songs / "target.json")
            settings = Settings(_path=root / "settings.json")
            selected: list[str] = []
            fake = SimpleNamespace(
                _pick_score=lambda sid: old if sid == "old" else None,
                _load_scores=lambda: load_scores(songs),
                _select_score=selected.append,
                settings=settings,
                scores=[old, other],
            )
            with patch.object(app_module, "data_dir", return_value=root):
                AppController._rename_score(fake, "old", "target")
            self.assertEqual(Score.load(songs / "target.json").id, "target")
            self.assertEqual(Score.load(songs / "target_2.json").name, "target")
            self.assertFalse((songs / "old.json").exists())
            self.assertEqual(selected, ["target_2"])

    def test_failed_rename_keeps_file_and_in_memory_score(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            songs = root / "scores"
            songs.mkdir()
            old = sample_score("old", "原曲")
            old.save(songs / "old.json")
            original = (songs / "old.json").read_bytes()
            fake = SimpleNamespace(_pick_score=lambda sid: old)
            with (patch.object(app_module, "data_dir", return_value=root),
                  patch.object(storage.os, "replace", side_effect=OSError("模拟写入失败"))):
                AppController._rename_score(fake, "old", "新曲名")
            self.assertEqual((songs / "old.json").read_bytes(), original)
            self.assertEqual((old.id, old.name), ("old", "原曲"))
            self.assertEqual(len(list(songs.glob("*.json"))), 1)

    def test_deleting_another_song_keeps_current_song_and_loop(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            songs = root / "scores"
            songs.mkdir()
            current = sample_score("current")
            other = sample_score("other")
            current.save(songs / "current.json")
            other.save(songs / "other.json")
            settings = Settings(_path=root / "settings.json")
            settings.last_score_id = "current"
            settings.loop_ranges = {"current": [0, 1], "other": [0, 1]}
            selections: list[str] = []
            sidebar = SimpleNamespace(set_scores=lambda scores, sid: selections.append(sid))
            fake = SimpleNamespace(
                _pick_score=lambda sid: other if sid == "other" else current,
                _load_scores=lambda: load_scores(songs),
                _select_score=lambda sid: self.fail("不应切换正在播放的曲目"),
                engine=SimpleNamespace(score=current),
                overlay=SimpleNamespace(sidebar=sidebar),
                settings=settings,
            )
            with patch.object(app_module, "data_dir", return_value=root):
                AppController._delete_score(fake, "other")
            self.assertEqual(selections, ["current"])
            self.assertEqual(settings.loop_ranges, {"current": [0, 1]})
            self.assertFalse((songs / "other.json").exists())

    def test_imported_score_id_cannot_delete_file_outside_scores(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "scores").mkdir()
            (root / "config").mkdir()
            settings_file = root / "config" / "settings.json"
            settings_file.write_text('{"keep":true}', encoding="utf-8")
            malicious = sample_score("../config/settings")
            fake = SimpleNamespace(
                _pick_score=lambda sid: malicious,
                engine=SimpleNamespace(score=sample_score("current")),
            )
            with patch.object(app_module, "data_dir", return_value=root):
                AppController._delete_score(fake, malicious.id)
            self.assertEqual(settings_file.read_text(encoding="utf-8"), '{"keep":true}')

    def test_loaded_score_identity_comes_from_its_filename(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "imported.json"
            sample_score("../config/settings").save(path)
            self.assertEqual(Score.load(path).id, "imported")


class PlaybackTests(unittest.TestCase):
    def test_basic_hotkeys_use_numpad_without_function_key_conflicts(self) -> None:
        expected = {
            "toggle_playback": (0, 0x67),
            "reset": (0, 0x68),
            "toggle_visible": (0, 0x69),
            "toggle_ball": (0, 0x6B),
        }
        self.assertEqual({name: HOTKEY_DEFS[name] for name in expected}, expected)
        self.assertEqual(len(set(HOTKEY_DEFS.values())), len(HOTKEY_DEFS))
        self.assertFalse(any(mods == 0 and 0x70 <= vk <= 0x73
                             for mods, vk in HOTKEY_DEFS.values()))
        self.assertEqual([cap for cap, _ in HOTKEY_HINTS[:4]], ["N7", "N8", "N9", "N+"])
        self.assertTrue(all("小键盘" in HOTKEY_LABELS[name] for name in expected))

    def test_cancel_calibration_restores_overlay_screen_profile(self) -> None:
        target = [KeyGeom(10.0, 20.0, 30.0)]
        with tempfile.TemporaryDirectory() as folder:
            saved = CalibrationData(
                profiles={"secondary": target, "primary": []},
                _path=Path(folder) / "calibration.json",
            )
            applied: list[object] = []
            fake = SimpleNamespace(
                calibration=SimpleNamespace(screen_key="secondary"),
                overlay=SimpleNamespace(apply_calibration=applied.append),
                _exit_calibration=lambda: None,
            )
            with patch.object(CalibrationData, "load", return_value=saved):
                AppController._cancel_calibration(fake)
            self.assertEqual(applied, [target])

    def test_reset_does_not_count_an_already_held_key_as_new_press(self) -> None:
        class FakeKeyboard:
            states = iter((0x8001, 0x8000))

            def GetAsyncKeyState(self, vk: int) -> int:
                return next(self.states)

        watcher = KeyWatcher({"Z": 0x5A})
        watcher._user32 = FakeKeyboard()
        watcher.reset()
        pressed, held = watcher.poll()
        self.assertEqual(pressed, [])
        self.assertEqual(held, {"Z"})

    def test_loop_range_rejects_out_of_song_and_normalizes_valid_input(self) -> None:
        engine = PlaybackEngine(sample_score(), count_in_beats=0)
        total = engine.total_ms()
        self.assertFalse(engine.set_loop_range(total + 100, total + 300))
        self.assertIsNone(engine.loop_range)
        self.assertTrue(engine.set_loop_range(total - 300, total + 300))
        self.assertEqual(engine.loop_range, (total - 300, total))

    def test_reload_detects_lyrics_only_change(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            songs = root / "scores"
            songs.mkdir()
            original = sample_score()
            updated = sample_score()
            updated.lyrics = [LyricLine(0.0, "新歌词")]
            updated.save(songs / "song.json")
            seen: list[Score] = []
            fake = SimpleNamespace(
                engine=PlaybackEngine(original, count_in_beats=0),
                scores=[original],
                _load_scores=lambda: load_scores(songs),
                _builtin_scores=lambda: [],
                _reset_feedback=lambda pos: None,
                _restore_loop_range=lambda score: None,
                overlay=SimpleNamespace(
                    set_score=seen.append,
                    sidebar=SimpleNamespace(set_scores=lambda scores, sid: None),
                ),
            )
            fake._pick_score = lambda sid: next((s for s in fake.scores if s.id == sid), None)
            AppController.reload_scores(fake)
            self.assertEqual(fake.engine.score.lyrics[0].text, "新歌词")
            self.assertEqual(len(seen), 1)


class EditorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_saving_existing_song_preserves_metadata(self) -> None:
        source = sample_score()
        source.time_signature = "3/4"
        source.lyrics = [LyricLine(500.0, "歌词")]
        editor = EditorWindow()
        editor.load_score(source)
        with tempfile.TemporaryDirectory() as folder:
            editor._save(Path(folder))
            saved = Score.load(Path(folder) / "song.json")
        self.assertEqual(saved.time_signature, "3/4")
        self.assertEqual(saved.keymap, source.keymap)
        self.assertEqual(saved.lyrics, source.lyrics)
        editor.close()

    def test_changing_bpm_keeps_lyrics_on_the_same_beat(self) -> None:
        source = sample_score()
        source.lyrics = [LyricLine(500.0, "第二拍")]
        editor = EditorWindow()
        editor.load_score(source)
        editor.bpm_spin.setValue(60)
        result = editor.build_score(source.id)
        self.assertEqual(result.lyrics[0].time_ms, 1000.0)
        editor.close()


if __name__ == "__main__":
    unittest.main()
