"""Real GIF decoding/rendering; no app windows or USB transfers."""
import os
import sys
import tempfile
from pathlib import Path
from unittest import TestCase, main
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PIL import Image
import studio_core as core
import screen_ui as ui
from keyboard_usb import build_buffer, PAGE_SIZE


class AnimationTests(TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / 'wallpaper.gif'
        self.write_gif(['red', 'green', 'blue'], [100, 400, 200])

    def tearDown(self):
        self.temp.cleanup()

    def write_gif(self, colors, delays):
        frames = [Image.new('RGB', (20, 20), color) for color in colors]
        frames[0].save(self.path, save_all=True, append_images=frames[1:],
                       duration=delays, disposal=2, loop=0)

    def test_wallpaper_timeline_retains_holds_and_wraps(self):
        animation = core.load_bg_animation(self.path)
        self.assertEqual(animation['starts'], [0, 100, 500])
        self.assertEqual(animation['duration'], 700)
        for tick, color in [(0, (255, 0, 0)), (499, (0, 128, 0)),
                            (500, (0, 0, 255)), (700, (255, 0, 0))]:
            self.assertEqual(core.background_at(animation, tick).getpixel((0, 0)), color)

    def test_replacing_wallpaper_invalidates_cache(self):
        old = core.load_bg_animation(self.path)
        stamp = self.path.stat().st_mtime_ns
        self.write_gif(['white', 'black'], [200, 200])
        os.utime(self.path, ns=(stamp + 10_000_000, stamp + 10_000_000))
        new = core.load_bg_animation(self.path)
        self.assertIsNot(old, new)
        self.assertEqual(new['frames'][0].getpixel((0, 0)), (255, 255, 255))

    def test_device_loop_animates_wallpaper_while_idle(self):
        frames, delays = ui.render_nowbar_frames(
            'nowbar_dual', {'available': False, 'bg_image_path': str(self.path)},
            {'cpu': 12, 'ram': 48}, mode='device_loop', frame_count=96, clock='21:30')
        self.assertEqual(len(frames), 3)  # No redundant copies of an idle GIF.
        self.assertLessEqual(len(frames), 96)
        self.assertGreater(len({frame.getpixel((0, 0)) for frame in frames}), 1)
        self.assertTrue(all(frame.size == (160, 96) for frame in frames))
        self.assertTrue(all(30 <= delay <= 500 and delay % 2 == 0 for delay in delays))
        self.assertEqual(delays, [100, 400, 200])
        blob = build_buffer(frames, delays)
        self.assertEqual(blob[0], len(frames))
        self.assertEqual(blob[1:len(frames) + 1], bytes(delay // 2 for delay in delays))
        self.assertEqual(len(blob) % PAGE_SIZE, 0)

    def test_long_title_gets_longer_cycle_and_independent_motion(self):
        media = {'available': True, 'playing': True, 'title': 'Very long song title ' * 4}
        with patch.object(ui, 'render_nowbar', return_value=Image.new('RGB', (160, 96))) as draw:
            frames, delays = ui.render_nowbar_frames('nowbar_media', media, {},
                                                    mode='device_loop', frame_count=96)
        self.assertGreaterEqual(sum(delays), 10_000)
        states = [call.args[1] for call in draw.call_args_list]
        self.assertEqual(states[0]['scroll_phase'], 0)
        self.assertTrue(all(state['hide_elapsed'] for state in states))
        # EQ repeats during the title's single readable scroll, with no claim
        # to predict future track progress or future CPU/RAM samples.
        self.assertGreater(sum(states[i]['motion_phase'] < states[i-1]['motion_phase']
                               for i in range(1, len(states))), 3)
        self.assertTrue(all(state.get('position') is None for state in states))

    def test_legacy_animated_mode_also_uses_more_than_first_gif_frame(self):
        frames, _ = ui.render_nowbar_frames('nowbar_dual',
                    {'bg_image_path': str(self.path)}, {}, mode='animated', frame_count=8)
        self.assertEqual(len(frames), 8)
        self.assertGreater(len({frame.getpixel((0, 0)) for frame in frames}), 1)

    def test_static_mode_remains_single_frame(self):
        frames, delays = ui.render_nowbar_frames('nowbar_dual',
                    {'bg_image_path': str(self.path)}, {}, mode='static')
        self.assertEqual((len(frames), delays), (1, [100]))

    def test_carousel_scroll_completes_while_media_panel_is_visible(self):
        with patch.object(ui, 'render_nowbar_media',
                          return_value=Image.new('RGB', (160, 96))) as draw:
            ui.render_nowbar('nowbar_carousel', {'scroll_phase': 0.42}, {}, phase=0.44)
        self.assertGreater(draw.call_args.args[0]['scroll_phase'], 0.99)

    def test_all_layouts_produce_valid_device_loops(self):
        for layout in ui.LAYOUTS:
            with self.subTest(layout=layout):
                frames, delays = ui.render_nowbar_frames(layout,
                    {'available': True, 'playing': True, 'title': 'Track',
                     'artist': 'Artist', 'duration': 180}, {'cpu': 20, 'ram': 40},
                    mode='device_loop', frame_count=96)
                self.assertEqual(len(frames), len(delays))
                self.assertTrue(all(frame.mode == 'RGB' and frame.size == (160, 96)
                                    for frame in frames))


if __name__ == '__main__':
    main()
