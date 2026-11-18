"""Language and demo isolation tests; no window, registry or USB is opened."""
from pathlib import Path
from string import Formatter
from types import SimpleNamespace
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import i18n
import studio


class Variable:
    def __init__(self, value):
        self.value = value
    def get(self):
        return self.value
    def set(self, value):
        self.value = value


class Label:
    def __init__(self):
        self.options = {}
    def configure(self, **kwargs):
        self.options.update(kwargs)


class LanguageTests(unittest.TestCase):
    def tearDown(self):
        i18n.set_language('en')

    def test_catalogue_templates_keep_the_same_placeholders(self):
        fields = lambda text: {name for _, name, _, _ in Formatter().parse(text) if name is not None}
        for source, english in i18n._EN.items():
            with self.subTest(message=source):
                self.assertEqual(fields(source), fields(english))

    def test_dynamic_messages_format_in_both_languages(self):
        key = 'USB yükleme hatası: {error} · Otomatik deneme {seconds} sn sonra.'
        i18n.set_language('en')
        self.assertEqual(i18n.t(key, error='busy', seconds=5),
                         'USB upload error: busy · Retrying in 5 s.')
        i18n.set_language('tr')
        self.assertEqual(i18n.t(key, error='busy', seconds=5),
                         'USB yükleme hatası: busy · Otomatik deneme 5 sn sonra.')

    def test_unknown_locale_defaults_to_english_without_changing_message_data(self):
        self.assertEqual(i18n.set_language('invalid'), 'en')
        self.assertEqual(i18n.t('Midnight Drive — {Live}'), 'Midnight Drive — {Live}')

    def test_language_change_waits_for_an_active_transfer(self):
        i18n.set_language('en')
        app = SimpleNamespace(language_var=Variable('Türkçe'), uploading=True,
                              gif_busy=False, status_var=Variable(''))
        studio.Studio.on_language_changed(app)
        self.assertEqual(i18n.get_language(), 'en')
        self.assertEqual(app.language_var.get(), 'English')
        self.assertIn('Wait', app.status_var.get())

    def test_language_is_a_design_event_without_enabling_uploads(self):
        from test_scheduler import Controller
        app = Controller()
        app._start_usb_upload = lambda *_args, **_kwargs: None
        i18n.set_language('en')
        app.maybe_auto_sync()
        i18n.set_language('tr')
        app.maybe_auto_sync()
        self.assertEqual(len(app.payload_modes), 2)
        app.auto_sync_var.set(False)
        i18n.set_language('en')
        app.maybe_auto_sync()
        self.assertEqual(len(app.payload_modes), 2)

    def test_language_rebuild_preserves_internal_choices_and_worker_objects(self):
        i18n.set_language('en')
        worker = object()
        destroyed, builds, tabs, saves = [], [], [], []
        app = SimpleNamespace(
            language_var=Variable('Türkçe'), uploading=False, gif_busy=False,
            current_theme_key=lambda: 'cover', current_sync_interval_key=lambda: 'event',
            layout_var=Variable('nowbar_dual'), layout_label_var=Variable('Dual'),
            theme_label_var=Variable('Cover'), sync_interval_var=Variable('On change'),
            bg_image_path='', bg_name_var=Variable('Default gradient'),
            cached_nowbar_frames=['old'], cached_nowbar_durations=[100],
            cached_nowbar_key=('old',), tab='nowbar',
            winfo_children=lambda: [SimpleNamespace(destroy=lambda: destroyed.append(True))],
            _build_ui=lambda: builds.append(True), switch_tab=tabs.append,
            persist_settings=lambda: saves.append(True), usb_label=Label(),
            usb_message='USB', usb_connected=False, status_var=Variable(''),
            _demo=False, upload_executor=worker,
        )
        studio.Studio.on_language_changed(app)
        self.assertEqual(i18n.get_language(), 'tr')
        self.assertEqual(app.layout_var.get(), 'nowbar_dual')
        self.assertIs(app.upload_executor, worker)
        self.assertEqual((destroyed, builds, tabs, saves), ([True], [True], ['nowbar'], [True]))
        self.assertIsNone(app.cached_nowbar_frames)
        self.assertEqual(app.sync_interval_map[app.sync_interval_var.get()], 'event')


class DemoIsolationTests(unittest.TestCase):
    def test_demo_never_polls_media_usb_or_system(self):
        app = SimpleNamespace(_demo=True, _closing=False, _quit_after_upload=False,
                              usb_label=Label())
        with patch.object(studio, 'system_stats') as stats, \
                patch.object(studio, 'media_info') as media, \
                patch.object(studio, 'check_connection') as usb:
            studio.Studio.refresh_telemetry(app)
            studio.Studio.refresh_usb_status(app)
        stats.assert_not_called()
        media.assert_not_called()
        usb.assert_not_called()

    def test_demo_blocks_upload_library_startup_and_settings_writes(self):
        app = SimpleNamespace(_demo=True, _initializing=False,
                              startup_var=Variable(True), status_var=Variable(''))
        with patch.object(studio, 'Keyboard') as keyboard, \
                patch.object(studio, 'add_to_driver') as library, \
                patch.object(studio, 'set_windows_startup') as startup, \
                patch.object(studio, 'save_settings') as settings:
            studio.Studio.maybe_auto_sync(app)
            studio.Studio._start_usb_upload(app, {'frames': []})
            studio.Studio.upload_usb_clicked(app)
            studio.Studio.register(app)
            studio.Studio.on_startup_toggled(app)
            studio.Studio.persist_settings(app)
        keyboard.assert_not_called()
        library.assert_not_called()
        startup.assert_not_called()
        settings.assert_not_called()
        self.assertFalse(app.startup_var.get())


if __name__ == '__main__':
    unittest.main()
