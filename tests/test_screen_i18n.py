"""Exercise the real 160x96 renderer in both languages without USB or a GUI."""
import sys
from pathlib import Path
from unittest import TestCase, main
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PIL import ImageDraw
from i18n import get_language, set_language, t
import screen_ui as ui


class ScreenLanguageTests(TestCase):
    def setUp(self):
        self.language = get_language()
        self.stats = {'cpu': 23, 'ram': 42, 'used': '6.7', 'total': '16'}

    def tearDown(self):
        set_language(self.language)

    def rendered_text(self, layout, media, note=''):
        drawn = []
        original = ImageDraw.ImageDraw.text

        def record(draw, xy, text, *args, **kwargs):
            drawn.append(str(text))
            return original(draw, xy, text, *args, **kwargs)

        with patch.object(ImageDraw.ImageDraw, 'text', record):
            image = ui.render_nowbar(layout, media, self.stats, label='STUDIO',
                                     custom_note=note, clock='21:30')
        self.assertEqual((image.size, image.mode), ((160, 96), 'RGB'))
        return drawn

    def test_every_screen_key_is_translated_and_formats_in_both_languages(self):
        for language in ('en', 'tr'):
            set_language(language)
            for source, english in ui.SCREEN_EN.items():
                with self.subTest(language=language, source=source):
                    expected = english if language == 'en' else source
                    self.assertEqual(t(source, time='03:20'), expected.format(time='03:20'))

    def test_all_layouts_render_both_languages_and_real_playback_states(self):
        for language in ('en', 'tr'):
            set_language(language)
            for layout in ui.LAYOUTS:
                for available, playing in ((False, False), (True, True), (True, False)):
                    with self.subTest(language=language, layout=layout,
                                      available=available, playing=playing):
                        texts = self.rendered_text(layout,
                            {'available': available, 'playing': playing,
                             'position': 95, 'duration': 218, 'hide_elapsed': True})
                        if language == 'en':
                            self.assertFalse(any(character in ''.join(texts)
                                                 for character in 'çğıöşüÇĞİÖŞÜ'))

    def test_language_switch_changes_screen_labels_without_changing_layout_ids(self):
        identifiers = tuple(ui.LAYOUTS)
        set_language('en')
        english = self.rendered_text('nowbar_media',
            {'available': True, 'playing': False})
        set_language('tr')
        turkish = self.rendered_text('nowbar_media',
            {'available': True, 'playing': False})
        self.assertIn('PAUSED', english)
        self.assertIn('DURAKLATILDI', turkish)
        self.assertEqual(tuple(ui.LAYOUTS), identifiers)

    def test_custom_text_and_song_metadata_are_never_translated(self):
        set_language('en')
        metadata = {'available': True, 'playing': True,
                    'title': 'Çağrı', 'artist': 'Güneş'}
        texts = self.rendered_text('nowbar_media', metadata)
        self.assertIn('Çağrı', texts)
        self.assertIn('Güneş', texts)
        texts = self.rendered_text('nowbar_dual', {'available': False}, 'Merhaba')
        self.assertIn('Merhaba', texts)

    def test_animation_frames_stay_upload_compatible_in_both_languages(self):
        for language in ('en', 'tr'):
            set_language(language)
            for layout in ui.LAYOUTS:
                with self.subTest(language=language, layout=layout):
                    frames, delays = ui.render_nowbar_frames(layout,
                        {'available': True, 'playing': True, 'title': 'Midnight Drive',
                         'artist': 'Studio Sessions', 'duration': 218}, self.stats,
                        mode='device_loop', frame_count=48, clock='21:30')
                    self.assertEqual(len(frames), len(delays))
                    self.assertTrue(all(frame.mode == 'RGB' and frame.size == (160, 96)
                                        for frame in frames))
                    self.assertTrue(all(30 <= delay <= 500 and delay % 2 == 0
                                        for delay in delays))


if __name__ == '__main__':
    main()
