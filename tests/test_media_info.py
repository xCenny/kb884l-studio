"""Isolated SMTC selection tests: no app import, GUI, USB, registry or network.

Only the two pure/source-level function definitions are compiled from the
production AST. WinRT and artwork retrieval are replaced with local fakes.
"""
import ast
import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from i18n import t
import i18n_backend

SOURCE = Path(__file__).resolve().parents[1] / 'studio_core.py'


class Session:
    def __init__(self, source, title, *, playing=False, artist='Artist', closed=False):
        self.source_app_user_model_id = source
        self.title = title
        self.playing = playing
        self.artist = artist
        self.closed = closed
        self.metadata_reads = 0

    def get_playback_info(self):
        return types.SimpleNamespace(playback_status=4 if self.playing else 5)

    async def try_get_media_properties_async(self):
        self.metadata_reads += 1
        if self.closed:
            raise RuntimeError('The media session has closed')
        return types.SimpleNamespace(title=self.title, artist=self.artist, thumbnail=None)

    def get_timeline_properties(self):
        return types.SimpleNamespace(
            start_time=timedelta(), end_time=timedelta(seconds=300),
            position=timedelta(seconds=60),
            last_updated_time=datetime(1970, 1, 1, tzinfo=timezone.utc),
        )


async def no_thumbnail(_reference):
    return None


def source_functions():
    module = ast.parse(SOURCE.read_text(encoding='utf-8'), filename=str(SOURCE))
    definitions = [node for node in module.body
                   if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                   and node.name in ('_media_source_label', 'media_info')]
    if len(definitions) != 2:
        raise AssertionError('Production media functions were not found')
    scope = {
        'datetime': datetime, 'timezone': timezone, 't': t,
        '_TRACK_COVER_CACHE': {},
        '_read_smtc_thumbnail': no_thumbnail,
        '_fetch_itunes_cover': lambda *_args: None,
        'register_cover_image': lambda _image: '',
    }
    exec(compile(ast.Module(body=definitions, type_ignores=[]), str(SOURCE), 'exec'), scope)
    return scope


def poll(sessions, current=None):
    scope = source_functions()
    manager = types.SimpleNamespace(get_sessions=lambda: sessions,
                                    get_current_session=lambda: current)

    class ManagerFactory:
        @staticmethod
        async def request_async():
            return manager

    modules = {}
    for name in ('winrt', 'winrt.windows', 'winrt.windows.media', 'winrt.windows.media.control'):
        module = types.ModuleType(name)
        module.__path__ = []
        modules[name] = module
    modules['winrt.windows.media.control'].GlobalSystemMediaTransportControlsSessionManager = ManagerFactory
    with patch.dict(sys.modules, modules):
        return asyncio.run(scope['media_info']())


class MediaSelectionTests(unittest.TestCase):
    def test_playing_browser_beats_paused_spotify(self):
        spotify = Session('Spotify', 'Paused Spotify')
        browser = Session('chrome.exe', 'Playing browser', playing=True)
        info = poll([spotify, browser], current=spotify)
        self.assertEqual(info['title'], 'Playing browser')
        self.assertTrue(info['playing'])
        self.assertEqual(spotify.metadata_reads, 0)

    def test_playing_spotify_keeps_priority_over_other_playing_media(self):
        browser = Session('chrome.exe', 'Browser', playing=True)
        spotify = Session('SpotifyAB.SpotifyMusic_zpdnekdrzrea0!Spotify', 'Spotify song', playing=True)
        info = poll([browser, spotify], current=browser)
        self.assertEqual(info['title'], 'Spotify song')
        self.assertEqual(info['source'], 'Spotify')

    def test_empty_sessions_return_idle(self):
        info = poll([])
        self.assertFalse(info['available'])
        self.assertFalse(info['playing'])
        self.assertEqual(info['position'], 0.0)

    def test_closed_session_returns_idle(self):
        info = poll([Session('Spotify', 'Closed', closed=True)])
        self.assertFalse(info['available'])
        self.assertEqual(info['source'], '')

    def test_closed_spotify_does_not_hide_playing_browser(self):
        closed = Session('Spotify', 'Closed', playing=True, closed=True)
        browser = Session('chrome.exe', 'Browser', playing=True)
        info = poll([closed, browser], current=closed)
        self.assertEqual(info['title'], 'Browser')
        self.assertTrue(info['playing'])

    def test_untitled_spotify_does_not_hide_named_playing_browser(self):
        untitled = Session('Spotify', '', playing=True)
        browser = Session('chrome.exe', 'Browser', playing=True)
        info = poll([untitled, browser], current=untitled)
        self.assertEqual(info['title'], 'Browser')
        self.assertEqual(untitled.metadata_reads, 1)

    def test_chrome_executable_source_label_and_missing_artist(self):
        info = poll([Session('chrome.exe', 'Video', playing=True, artist='')])
        self.assertEqual(info['source'], 'chrome')
        self.assertEqual(info['artist'], 'chrome')

    def test_paused_spotify_remains_fallback_when_nothing_is_playing(self):
        browser = Session('chrome.exe', 'Paused browser')
        spotify = Session('Spotify', 'Paused Spotify')
        info = poll([browser, spotify], current=browser)
        self.assertEqual(info['title'], 'Paused Spotify')
        self.assertFalse(info['playing'])

    def test_selected_timeline_values_are_preserved(self):
        info = poll([Session('chrome.exe', 'Video', playing=True)])
        self.assertEqual(info['position'], 60.0)
        self.assertEqual(info['duration'], 300.0)


class SourceLabelTests(unittest.TestCase):
    def test_win32_and_packaged_names(self):
        label = source_functions()['_media_source_label']
        samples = {
            'chrome.exe': 'chrome',
            'Spotify.EXE': 'Spotify',
            r'C:\Program Files\Browser\chrome.exe': 'chrome',
            'SpotifyAB.SpotifyMusic_zpdnekdrzrea0!Spotify': 'Spotify',
            'Microsoft.ZuneMusic_8wekyb3d8bbwe!App': 'ZuneMusic',
            'org.chromium.Chromium': 'Chromium',
            '': '',
        }
        for source, expected in samples.items():
            with self.subTest(source=source):
                self.assertEqual(label(source), expected)


if __name__ == '__main__':
    unittest.main()
