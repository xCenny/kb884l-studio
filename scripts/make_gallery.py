"""Render synthetic README assets using the real display renderer. No USB/network."""
from pathlib import Path
import math
import sys
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from i18n import set_language
from studio_core import font, register_cover_image, save_gif
from screen_ui import render_nowbar, render_nowbar_frames


def main():
    set_language('en')
    out = ROOT/'docs/images'
    out.mkdir(parents=True, exist_ok=True)
    cover = Image.new('RGB', (128, 128))
    pixels = cover.load()
    for y in range(128):
        for x in range(128):
            glow = max(0, 1-math.hypot(x-82, y-48)/90)
            pixels[x, y] = (int(20+72*glow), int(15+y*.3+65*glow), int(50+x*.5+75*glow))
    d = ImageDraw.Draw(cover)
    for radius in (22, 34, 46):
        d.ellipse((64-radius, 64-radius, 64+radius, 64+radius), outline='#78e5e3', width=2)
    d.line((16, 99, 112, 35), fill='#fba9df', width=4)
    media = {'available': True, 'playing': True, 'title': 'Midnight Drive',
             'artist': 'Studio Sessions', 'source': 'Spotify', 'duration': 224,
             'position': 73, 'cover_hash': register_cover_image(cover), 'hide_elapsed': True}
    stats = {'cpu': 24, 'ram': 46, 'used': '7.4', 'total': '16'}
    cards = {}
    for short in ('dual', 'artwork', 'media', 'system', 'carousel'):
        image = render_nowbar('nowbar_'+short, media, stats, 'cover', 'STUDIO',
                              'Ready for your next track', phase=.18, clock='17:42')
        cards[short] = image
        image.resize((640, 384), Image.Resampling.NEAREST).save(out/f'{short}.png')
    frames, delays = render_nowbar_frames('nowbar_media', media, stats, 'cover',
                        'STUDIO', mode='device_loop', frame_count=96, clock='17:42')
    save_gif({'frames': [f.resize((480, 288), Image.Resampling.NEAREST) for f in frames],
              'durations': delays}, out/'nowbar-loop.gif')
    hero = Image.new('RGB', (1440, 840), '#0b1019')
    d = ImageDraw.Draw(hero)
    d.rounded_rectangle((40, 32, 1400, 808), radius=32, outline='#25374e', width=2)
    d.text((82, 66), 'KB884L STUDIO', font=font(22, True), fill='#67d9ef')
    d.text((82, 112), 'A small screen.', font=font(52, True), fill='#f0f5ff')
    d.text((82, 174), 'A more personal desktop.', font=font(52, True), fill='#f0f5ff')
    d.text((84, 260), 'Windows  /  160 × 96  /  English + Türkçe', font=font(22), fill='#9caec5')
    positions = [('dual', 82, 350), ('artwork', 530, 350), ('media', 978, 350)]
    for name, x, y in positions:
        d.rounded_rectangle((x-10, y-10, x+394, y+240), radius=18, fill='#151f30', outline='#2e4560', width=2)
        hero.paste(cards[name].resize((384, 230), Image.Resampling.NEAREST), (x, y))
        d.text((x, y+264), name.upper(), font=font(18, True), fill='#a9bad0')
    d.line((82, 696, 1354, 696), fill='#273850', width=2)
    d.text((84, 726), 'Design · Preview · Upload', font=font(25, True), fill='#67d9ef')
    d.text((955, 734), 'Independent community project', font=font(17), fill='#8194af')
    hero.save(out/'hero.png')
    print('Gallery generated from synthetic metadata and original procedural artwork.')


if __name__ == '__main__':
    main()
