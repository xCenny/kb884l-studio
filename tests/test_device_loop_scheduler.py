"""Device playback behavior without opening a window or touching USB."""
from pathlib import Path
from types import SimpleNamespace
import sys
from unittest import TestCase, main
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import studio
from test_scheduler import Controller, Variable, Widget


class DeviceLoopSchedulingTests(TestCase):
    def setUp(self):
        self.now = 100.0
        self.clock = '12:00'
        self.monotonic = patch.object(studio.time, 'monotonic', lambda: self.now)
        self.monotonic.start()
        self.datetime = patch.object(studio, 'datetime')
        self.mock_datetime = self.datetime.start()
        self.mock_datetime.now.return_value.strftime.side_effect = lambda _fmt: self.clock

    def tearDown(self):
        self.datetime.stop()
        self.monotonic.stop()

    def controller(self):
        app = Controller()
        app.mode = 'device_loop'
        app.is_media_playing = lambda: bool(app.info.get('available') and app.info.get('playing'))
        app._start_usb_upload = lambda *args, **kwargs: None
        return app

    def test_loop_ignores_periodic_time_and_system_changes(self):
        for interval in ('event', '1m', '30s'):
            with self.subTest(interval=interval):
                app = self.controller()
                app.interval = interval
                app.idle_clock_sync_var.set(True)
                app.maybe_auto_sync()
                self.now += 120
                self.clock = '12:02'
                app.stats = {'cpu': 99, 'ram': 95}
                app.info['position'] = 120
                app.maybe_auto_sync()
                self.assertEqual(app.payload_modes, ['device_loop'])

    def test_loop_updates_for_real_metadata_playback_and_design_events(self):
        app = self.controller()
        app.maybe_auto_sync()
        for field, value in (('source', 'Spotify'), ('title', 'Next Track'), ('artist', 'Other Artist'), ('playing', False)):
            app.info[field] = value
            app.maybe_auto_sync()
        app.label_var.set('NEW')
        app.maybe_auto_sync()
        self.assertEqual(app.payload_modes, ['device_loop'] * 6)

    def test_loop_force_still_resends_and_backoff_still_applies(self):
        app = self.controller()
        app.maybe_auto_sync()
        app._next_retry_at = 500
        app.info['title'] = 'Pending Track'
        app.maybe_auto_sync()
        self.assertEqual(len(app.payload_modes), 1)
        app.maybe_auto_sync(force=True)
        self.assertEqual(len(app.payload_modes), 2)

    def test_idle_media_preserves_selected_animation_mode(self):
        app = SimpleNamespace(mode_var=Variable('device_loop'), is_media_playing=lambda: False)
        self.assertEqual(studio.Studio.effective_mode(app), 'device_loop')
        self.assertEqual(studio.Studio.effective_mode(app, 'animated'), 'animated')

    def test_device_loop_payload_requests_new_renderer_and_hides_elapsed(self):
        app = SimpleNamespace(
            effective_layout=lambda: 'nowbar_dual', current_theme_key=lambda: 'cover',
            label_var=Variable('CAN'), note_var=Variable('idle'),
            effective_mode=lambda override: 'device_loop', current_sync_interval_key=lambda: '30s',
            info={'available': False}, stats={'cpu': 10, 'ram': 50}, bg_image_path='wallpaper.gif',
        )
        with patch.object(studio, 'render_nowbar_frames', return_value=(['frame'], [80])) as render:
            payload = studio.Studio.build_nowbar_media(app)
        args, kwargs = render.call_args
        self.assertTrue(args[1]['hide_elapsed'])
        self.assertEqual(kwargs['mode'], 'device_loop')
        self.assertEqual(kwargs['frame_count'], 96)
        self.assertEqual(payload['durations'], [80])


class DeviceLoopPreviewTests(TestCase):
    def test_hidden_window_does_not_generate_preview(self):
        app = SimpleNamespace(state=lambda: 'withdrawn')
        with patch.object(studio, 'render_nowbar_frames') as render:
            studio.Studio.render_nowbar_preview_now(app)
        render.assert_not_called()

    def test_preview_uses_payload_durations_and_keeps_snapshot_cached(self):
        calls, shown, scheduled = [], [], []
        app = SimpleNamespace(
            tab='nowbar', state=lambda: 'normal',
            effective_layout=lambda: 'nowbar_dual', current_theme_key=lambda: 'cover',
            effective_mode=lambda: 'device_loop', current_sync_interval_key=lambda: '1m',
            label_var=Variable('CAN'), note_var=Variable('idle'), bg_image_path='',
            info={'available': True, 'playing': True, 'title': 'Track', 'artist': 'Artist'},
            stats={'cpu': 10, 'ram': 50}, cached_nowbar_frames=None,
            cached_nowbar_durations=None, cached_nowbar_key=None,
            preview_anim_step=0, _preview_delay=120, details=Widget(),
        )
        def build(**kwargs):
            calls.append(kwargs)
            return {'frames': ['frame-0', 'frame-1'], 'durations': [40, 170]}
        app.build_nowbar_media = build
        app.show_image = shown.append
        app.after = lambda delay, callback: scheduled.append(delay)
        app.render_nowbar_preview_now = lambda: studio.Studio.render_nowbar_preview_now(app)
        app.animate = lambda: studio.Studio.animate(app)
        app.animate()
        app.stats = {'cpu': 99, 'ram': 95}
        app.info['position'] = 32
        app.animate()
        self.assertEqual(len(calls), 1)
        self.assertEqual(shown, ['frame-0', 'frame-1'])
        self.assertEqual(scheduled, [40, 170])


if __name__ == '__main__':
    main()
