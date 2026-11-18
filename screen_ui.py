"""Host-side 160x96 Now Bar renderer for the keyboard's animation player."""
from __future__ import annotations
import colorsys
from datetime import datetime, timedelta
import math
import time
from PIL import Image, ImageDraw, ImageOps
from i18n import register_translations, t
from studio_core import (font, clip_text, get_cover_image, load_bg_image,
                         load_bg_animation, background_at)

SIZE = (160, 96)

# Register screen text separately from the desktop UI. Keys remain Turkish so
# saved layout/theme IDs and user-provided song titles never need translation.
SCREEN_EN = {
    'Albüm Kapağı (Dinamik Renk)': 'Album artwork (dynamic colors)',
    'Galaxy Mavi': 'Galaxy blue',
    'Spotify Yeşil': 'Spotify green',
    'Gün Batımı Turuncu': 'Sunset orange',
    'Siber Pembe': 'Cyber pink',
    'OLED Beyaz': 'OLED white',
    'İkili Now Bar (Saat/Sistem + Kapaklı Hap)': 'Dual Now Bar (clock, system + media pill)',
    'Vitrin Now Bar (Büyük Albüm Kapağı + Saat)': 'Artwork Now Bar (large cover + clock)',
    'Medya Now Bar (Büyük Kapak & Kapsül)': 'Media Now Bar (cover + capsule)',
    'Sistem Now Bar (CPU & RAM Kapsülü)': 'System Now Bar (CPU + RAM capsules)',
    'Dönüşümlü Now Bar (Medya ↔ Sistem)': 'Carousel Now Bar (media ↔ system)',
    'Çalan Parça': 'Now playing',
    'Medya': 'Media',
    'Hazır · Now Bar': 'Ready · Now Bar',
    'SÜRE {time}': 'TOTAL {time}',
    'ÇALIYOR': 'PLAYING',
    'DURAKLATILDI': 'PAUSED',
    'Bilinmeyen Parça': 'Unknown track',
    'BEKLEMEDE': 'STANDBY',
    'Medya bekleniyor': 'Waiting for media',
    'Spotify veya tarayıcı aç': 'Open Spotify or a browser',
    'Süre: {time}': 'Total: {time}',
    'DURAKLAT': 'PAUSED',
    'HAZIR': 'READY',
    'SİSTEM': 'SYSTEM',
    'İŞLEMCİ (CPU)': 'PROCESSOR (CPU)',
    'MÜZİK': 'MUSIC',
    'BİLDİRİM': 'NOTICE',
    'Müzik': 'Music',
    'Sistem': 'System',
    'Uyarı': 'Alerts',
    'Spotify hazır': 'Spotify ready',
    'Bir şarkı aç': 'Play a track',
    'Bildirim': 'Notification',
    'Yeni bildirim': 'New notification',
    'Bildirimler': 'Notifications',
    'Her şey sakin': 'All clear',
    'Yeni bildirimler burada görünecek.': 'New notifications will appear here.',
}
register_translations(SCREEN_EN)

# Legacy constants preserved for backwards compatibility
BG = '#090e17'
PANEL = '#151f30'
TEXT = '#eef3fb'
MUTED = '#91a1b8'
ACCENTS = {'spotify': '#3be287', 'system': '#70d4f5', 'notification': '#ffbd77'}

THEMES = {
    'cover': {
        'name': 'Albüm Kapağı (Dinamik Renk)',
        'bg': '#070b14',
        'pill': '#131d31',
        'pill_border': '#273c63',
        'badge': '#192c4d',
        'accent': '#5ce1e6',
        'accent2': '#7b61ff',
        'text': '#f1f5ff',
        'muted': '#8ea2c0',
        'track': '#1f304f',
    },
    'galaxy': {
        'name': 'Galaxy Mavi',
        'bg': '#070b14',
        'pill': '#131d31',
        'pill_border': '#273c63',
        'badge': '#192c4d',
        'accent': '#5ce1e6',
        'accent2': '#7b61ff',
        'text': '#f1f5ff',
        'muted': '#8ea2c0',
        'track': '#1f304f',
    },
    'spotify': {
        'name': 'Spotify Yeşil',
        'bg': '#06110b',
        'pill': '#102419',
        'pill_border': '#1e4630',
        'badge': '#143a25',
        'accent': '#1ed760',
        'accent2': '#5de393',
        'text': '#f0fbf4',
        'muted': '#90b39e',
        'track': '#1c3b29',
    },
    'sunset': {
        'name': 'Gün Batımı Turuncu',
        'bg': '#140908',
        'pill': '#291512',
        'pill_border': '#522923',
        'badge': '#3d1d17',
        'accent': '#ff7b54',
        'accent2': '#ffb26b',
        'text': '#fff4ef',
        'muted': '#c49d92',
        'track': '#44221d',
    },
    'cyber': {
        'name': 'Siber Pembe',
        'bg': '#0d0618',
        'pill': '#1f1135',
        'pill_border': '#462478',
        'badge': '#331757',
        'accent': '#ff2a85',
        'accent2': '#00e5ff',
        'text': '#f8f0ff',
        'muted': '#b297cf',
        'track': '#371d5e',
    },
    'oled': {
        'name': 'OLED Beyaz',
        'bg': '#000000',
        'pill': '#16181d',
        'pill_border': '#333845',
        'badge': '#242933',
        'accent': '#ffffff',
        'accent2': '#9ec0ff',
        'text': '#ffffff',
        'muted': '#9aa3b2',
        'track': '#2b303a',
    },
}

LAYOUTS = {
    'nowbar_dual': 'İkili Now Bar (Saat/Sistem + Kapaklı Hap)',
    'nowbar_artwork': 'Vitrin Now Bar (Büyük Albüm Kapağı + Saat)',
    'nowbar_media': 'Medya Now Bar (Büyük Kapak & Kapsül)',
    'nowbar_system': 'Sistem Now Bar (CPU & RAM Kapsülü)',
    'nowbar_carousel': 'Dönüşümlü Now Bar (Medya ↔ Sistem)',
}


def _hex(rgb):
    return f'#{max(0, min(255, int(rgb[0]))):02x}{max(0, min(255, int(rgb[1]))):02x}{max(0, min(255, int(rgb[2]))):02x}'


def _mix(c1, c2, t):
    return (
        c1[0] * (1.0 - t) + c2[0] * t,
        c1[1] * (1.0 - t) + c2[1] * t,
        c1[2] * (1.0 - t) + c2[2] * t,
    )


def _theme(theme_key):
    return THEMES.get(theme_key, THEMES['galaxy'])


def _resolve_theme(theme_key, cover_img=None):
    base = dict(_theme(theme_key))
    if theme_key != 'cover' or cover_img is None:
        return base
    try:
        sample = cover_img.convert('RGB').resize((20, 20), Image.Resampling.BILINEAR)
        raw = sample.tobytes()
        pixels = [(raw[i], raw[i + 1], raw[i + 2]) for i in range(0, len(raw), 3)]
        if not pixels:
            return base
        avg = (
            sum(p[0] for p in pixels) / len(pixels),
            sum(p[1] for p in pixels) / len(pixels),
            sum(p[2] for p in pixels) / len(pixels),
        )
        best_rgb = None
        best_score = -1.0
        for r, g, b in pixels:
            _h, s, v = colorsys.rgb_to_hsv(r / 255.0, g / 255.0, b / 255.0)
            if v < 0.22:
                continue
            score = s * (0.35 + 0.65 * v) + (0.08 * v if s < 0.15 else 0.0)
            if score > best_score:
                best_score = score
                best_rgb = (r, g, b)
        if best_rgb is None:
            accent_rgb = (92, 225, 230)
        else:
            h, s, v = colorsys.rgb_to_hsv(best_rgb[0] / 255.0, best_rgb[1] / 255.0, best_rgb[2] / 255.0)
            if s < 0.12:
                accent_rgb = (225, 232, 245)
            else:
                r2, g2, b2 = colorsys.hsv_to_rgb(h, max(0.55, s), max(0.88, v))
                accent_rgb = (r2 * 255.0, g2 * 255.0, b2 * 255.0)
        ah, asat, aval = colorsys.rgb_to_hsv(accent_rgb[0] / 255.0, accent_rgb[1] / 255.0, accent_rgb[2] / 255.0)
        r3, g3, b3 = colorsys.hsv_to_rgb((ah + 0.11) % 1.0, max(0.45, asat * 0.85), max(0.85, aval))
        accent2_rgb = (r3 * 255.0, g3 * 255.0, b3 * 255.0)

        bg_rgb = _mix((avg[0] * 0.15, avg[1] * 0.15, avg[2] * 0.15), (7, 9, 15), 0.30)
        pill_rgb = _mix((avg[0] * 0.28, avg[1] * 0.28, avg[2] * 0.28), (15, 19, 30), 0.25)
        border_rgb = _mix(pill_rgb, accent_rgb, 0.42)
        badge_rgb = _mix(pill_rgb, accent2_rgb, 0.28)
        track_rgb = _mix(pill_rgb, accent_rgb, 0.20)
        muted_rgb = _mix((190, 200, 218), accent_rgb, 0.22)
        return {
            'name': base['name'],
            'bg': _hex(bg_rgb),
            'pill': _hex(pill_rgb),
            'pill_border': _hex(border_rgb),
            'badge': _hex(badge_rgb),
            'accent': _hex(accent_rgb),
            'accent2': _hex(accent2_rgb),
            'text': '#f4f7ff',
            'muted': _hex(muted_rgb),
            'track': _hex(track_rgb),
        }
    except Exception:
        return base


def _paste_rounded_cover(canvas, cover_img, x, y, size, radius=8, border_color=None):
    fitted = ImageOps.fit(cover_img.convert('RGB'), (size, size), method=Image.Resampling.LANCZOS)
    mask = Image.new('L', (size, size), 0)
    md = ImageDraw.Draw(mask)
    md.rounded_rectangle((0, 0, size - 1, size - 1), radius=radius, fill=255)
    canvas.paste(fitted, (x, y), mask)
    if border_color:
        d = ImageDraw.Draw(canvas)
        d.rounded_rectangle((x, y, x + size - 1, y + size - 1), radius=radius, outline=border_color, width=1)


def _ambient_pill(canvas, cover_img, box, radius, pill_hex, border_color):
    x1, y1, x2, y2 = box
    w, h = x2 - x1 + 1, y2 - y1 + 1
    base = Image.new('RGB', (w, h), pill_hex)
    if cover_img is not None:
        tiny = ImageOps.fit(cover_img.convert('RGB'), (16, 10), method=Image.Resampling.BILINEAR)
        glow = tiny.resize((w, h), Image.Resampling.BILINEAR)
        glow = glow.point(lambda c: int(c * 0.26))
        blended = Image.blend(base, glow, 0.55)
    else:
        blended = base
    mask = Image.new('L', (w, h), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, w - 1, h - 1), radius=radius, fill=255)
    canvas.paste(blended, (x1, y1), mask)
    ImageDraw.Draw(canvas).rounded_rectangle(box, radius=radius, outline=border_color, width=1)


def _draw_mini_eq(draw, x, y, h, theme, playing, phase=None, bars=4):
    if not playing:
        return
    p = 0.25 if phase is None else phase
    bottom_y = y + h
    for i in range(bars):
        level = 0.30 + 0.70 * (0.5 + 0.5 * math.sin(p * 2 * math.pi + i * 1.4))
        bh = max(2, int(round(h * level)))
        bx = x + i * 3
        color = theme['accent'] if i % 2 == 0 else theme['accent2']
        draw.rectangle((bx, bottom_y - bh, bx + 1, bottom_y), fill=color)


def _rgb(hex_color):
    s = hex_color.lstrip('#')
    return (int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16))


def _draw_glass_box(canvas, box, radius, fill_rgb, alpha=165, outline_color=None):
    x1, y1, x2, y2 = box
    w, h = x2 - x1 + 1, y2 - y1 + 1
    crop = canvas.crop((x1, y1, x2 + 1, y2 + 1)).convert('RGBA')
    overlay = Image.new('RGBA', (w, h), (0, 0, 0, 0))
    od = ImageDraw.Draw(overlay)
    od.rounded_rectangle((0, 0, w - 1, h - 1), radius=radius, fill=(*fill_rgb, alpha))
    composited = Image.alpha_composite(crop, overlay).convert('RGB')
    canvas.paste(composited, (x1, y1))
    if outline_color:
        ImageDraw.Draw(canvas).rounded_rectangle(box, radius=radius, outline=outline_color, width=1)


def _prepare_dual_background(theme, bg_img=None):
    if bg_img is not None:
        fitted = ImageOps.fit(bg_img.convert('RGB'), SIZE, method=Image.Resampling.LANCZOS)
        return fitted.point(lambda c: int(c * 0.68))
    top = _rgb(theme['bg'])
    bot = _mix(_rgb(theme['bg']), _rgb(theme['pill']), 0.68)
    accent = _rgb(theme['accent2'])
    grad = Image.new('RGB', SIZE, top)
    gd = ImageDraw.Draw(grad)
    for y in range(SIZE[1]):
        t = y / max(1, SIZE[1] - 1)
        row_rgb = _mix(top, bot, t * t)
        if y > 48:
            row_rgb = _mix(row_rgb, accent, (y - 48) / 48.0 * 0.14)
        gd.line((0, y, SIZE[0] - 1, y), fill=_hex(row_rgb))
    return grad


def _draw_wave_scrubber(image, x1, x2, cy, ratio, theme, available=True, playing=True, phase=None):
    """Draw a One UI 7 layered-wave progress bar with a hollow circular scrubber ring."""
    pad_x = 6
    top_pad = 9
    bot_pad = 6
    w = (x2 - x1) + pad_x * 2 + 1
    h = top_pad + bot_pad + 1
    s = 2  # 2x supersampling for smooth anti-aliased wave ribbons and ring
    overlay = Image.new('RGBA', (w * s, h * s), (0, 0, 0, 0))
    od = ImageDraw.Draw(overlay)

    cx1 = pad_x * s
    cx2 = (pad_x + (x2 - x1)) * s
    ccy = top_pad * s
    span = cx2 - cx1
    ring_r = 4.2 * s

    pos_r = max(0.26, min(0.92, float(ratio or 0.0))) if available else max(0.14, min(0.92, float(ratio or 0.35)))
    rx = cx1 + int(round(span * pos_r))

    def _irgb(c):
        return (max(0, min(255, int(round(c[0])))),
                max(0, min(255, int(round(c[1])))),
                max(0, min(255, int(round(c[2])))))

    track_rgb = _irgb(_mix(_rgb(theme['track']), (145, 155, 175), 0.42))
    accent_rgb = _rgb(theme['accent'])
    accent2_rgb = _rgb(theme['accent2'])
    pill_rgb = _rgb(theme['pill'])
    base_played_rgb = _irgb(_mix(accent_rgb, (52, 74, 116), 0.45))

    # Muted unplayed track on the right of the circular ring
    right_start = min(cx2 - s, int(round(rx + ring_r + 1.5 * s)))
    if right_start < cx2:
        od.rounded_rectangle(
            (right_start, ccy - 3, cx2, ccy + 3),
            radius=3,
            fill=(*track_rgb, 210),
        )

    # Three overlapping translucent sine waves rising above the played left segment
    wx1 = cx1 + s
    wx2 = max(wx1 + 4, int(round(rx - ring_r - 0.5 * s)))
    wlen = wx2 - wx1
    if wlen >= 6 * s:
        p = 0.25 if phase is None else float(phase)
        amp_scale = 1.0 if (available and playing) else 0.28
        base_y = ccy - 2
        steps = max(24, wlen // s)
        layers = (
            (accent2_rgb, 110, 1.7, p * 2 * math.pi, 5.4 * s),
            (_irgb(_mix(accent_rgb, (210, 218, 232), 0.45)), 145, 2.3, -p * 2 * math.pi + 1.1, 6.2 * s),
            ((242, 246, 255), 195, 1.45, p * 2 * math.pi + 2.4, 5.0 * s),
        )
        for col, alpha, freq, shift, max_amp in layers:
            pts = [(wx1, base_y)]
            for k in range(steps + 1):
                t = k / steps
                env = math.sin(math.pi * t) ** 0.85
                wave = 0.5 + 0.5 * math.sin(t * freq * 2 * math.pi + shift)
                py = base_y - (max_amp * amp_scale * env * wave)
                pts.append((int(round(wx1 + t * wlen)), int(round(py))))
            pts.append((wx2, base_y))
            od.polygon(pts, fill=(*col, alpha))

    # Played left base bar
    left_end = max(cx1 + 2 * s, int(round(rx - ring_r + 0.5 * s)))
    od.rounded_rectangle(
        (cx1, ccy - 3, left_end, ccy + 3),
        radius=3,
        fill=(*base_played_rgb, 245),
    )

    # Soft glow + bright hollow circular scrubber ring
    glow_r = int(round(6.0 * s))
    od.ellipse((rx - glow_r, ccy - glow_r, rx + glow_r, ccy + glow_r), fill=(*accent_rgb, 55))
    outer_r = int(round(ring_r))
    od.ellipse((rx - outer_r, ccy - outer_r, rx + outer_r, ccy + outer_r), fill=(250, 252, 255, 255))
    inner_r = int(round(2.6 * s))
    od.ellipse((rx - inner_r, ccy - inner_r, rx + inner_r, ccy + inner_r), fill=(*pill_rgb, 255))

    downsampled = overlay.resize((w, h), Image.Resampling.LANCZOS)
    x0 = x1 - pad_x
    y0 = cy - top_pad
    crop = image.crop((x0, y0, x0 + w, y0 + h)).convert('RGBA')
    composited = Image.alpha_composite(crop, downsampled).convert('RGB')
    image.paste(composited, (x0, y0))


def _format_mmss(seconds):
    total = max(0, int(seconds or 0))
    return f'{total // 60:02d}:{total % 60:02d}'


def _draw_scrolling_text(image, x, y, width, height, text, typeface, fill, bg, phase=None):
    """Draw single-line text clipped cleanly to (x, y, width, height), scrolling if animated."""
    text = str(text or '').strip()
    if not text or width <= 4:
        return
    if bg is None:
        base_crop = image.crop((x, y, x + width, y + height)).convert('RGBA')
        strip = Image.new('RGBA', (width, height), (0, 0, 0, 0))
    else:
        strip = Image.new('RGB', (width, height), bg)
    sd = ImageDraw.Draw(strip)
    text_w = sd.textlength(text, font=typeface)
    if text_w <= width:
        sd.text((0, 0), text, font=typeface, fill=fill)
    elif phase is None:
        sd.text((0, 0), clip_text(sd, text, typeface, width), font=typeface, fill=fill)
    else:
        loop_text = text + '   •   '
        cycle = sd.textlength(loop_text, font=typeface)
        shift = int((phase % 1.0) * cycle)
        sd.text((-shift, 0), loop_text, font=typeface, fill=fill)
        sd.text((int(round(cycle)) - shift, 0), loop_text, font=typeface, fill=fill)
    if bg is None:
        merged = Image.alpha_composite(base_crop, strip).convert('RGB')
        image.paste(merged, (x, y))
    else:
        image.paste(strip, (x, y))


def _draw_eq_or_icon(draw, cx, cy, size, theme, available, playing, phase=None, bars=4):
    """Draw animated equalizer bars when playing, pause/play or idle icon otherwise."""
    accent = theme['accent']
    accent2 = theme['accent2']
    if available and playing:
        bar_w = 2 if bars >= 5 else 3
        gap = 2
        total_w = bars * bar_w + (bars - 1) * gap
        start_x = cx - total_w // 2
        max_h = size
        bottom_y = cy + max_h // 2
        p = 0.25 if phase is None else phase
        for i in range(bars):
            level = 0.28 + 0.72 * (0.5 + 0.5 * math.sin(p * 2 * math.pi + i * 1.35))
            bh = max(3, int(round(max_h * level)))
            bx = start_x + i * (bar_w + gap)
            bar_color = accent if i % 2 == 0 else accent2
            draw.rounded_rectangle((bx, bottom_y - bh, bx + bar_w, bottom_y), radius=1, fill=bar_color)
    elif available:
        # Pause bars
        bw = max(2, size // 5)
        bh = max(8, int(size * 0.72))
        gap = max(2, bw)
        lx = cx - gap // 2 - bw
        rx = cx + gap // 2 + 1
        top = cy - bh // 2
        draw.rounded_rectangle((lx, top, lx + bw, top + bh), radius=1, fill=accent)
        draw.rounded_rectangle((rx, top, rx + bw, top + bh), radius=1, fill=accent)
    else:
        # Idle sparkle / waveform pulse
        r = max(4, size // 3)
        draw.polygon(
            ((cx, cy - r), (cx + 2, cy - 2), (cx + r, cy), (cx + 2, cy + 2),
             (cx, cy + r), (cx - 2, cy + 2), (cx - r, cy), (cx - 2, cy - 2)),
            fill=accent,
        )


def _draw_top_bar(draw, theme, tag, right_text):
    rw = draw.textlength(right_text, font=font(8, True))
    rx = max(80, int(153 - rw))
    max_tag_w = max(48, rx - 12)
    draw.text((7, 1), clip_text(draw, tag, font(8, True), max_tag_w), font=font(8, True), fill=theme['accent'])
    draw.text((rx, 1), right_text, font=font(8, True), fill=theme['text'])
    draw.line((6, 14, 153, 14), fill=theme['pill_border'], width=1)


def _draw_cpu_icon(draw, cx, cy, color):
    draw.rounded_rectangle((cx - 5, cy - 5, cx + 5, cy + 5), radius=2, outline=color, width=1)
    draw.rectangle((cx - 2, cy - 2, cx + 2, cy + 2), fill=color)
    for d in (-3, 0, 3):
        draw.line((cx + d, cy - 7, cx + d, cy - 5), fill=color, width=1)
        draw.line((cx + d, cy + 5, cx + d, cy + 7), fill=color, width=1)
        draw.line((cx - 7, cy + d, cx - 5, cy + d), fill=color, width=1)
        draw.line((cx + 5, cy + d, cx + 7, cy + d), fill=color, width=1)


def _draw_ram_icon(draw, cx, cy, color):
    draw.rounded_rectangle((cx - 6, cy - 4, cx + 6, cy + 3), radius=1, outline=color, width=1)
    for dx in (-3, 0, 3):
        draw.rectangle((cx + dx - 1, cy - 2, cx + dx + 1, cy + 1), fill=color)
        draw.line((cx + dx, cy + 3, cx + dx, cy + 6), fill=color, width=1)


def render_nowbar_dual(media, stats, theme_key='galaxy', label='STUDIO', custom_note='', phase=None, clock=None):
    motion_phase = media.get('motion_phase', phase)
    cover_img = get_cover_image(media)
    theme = _resolve_theme(theme_key, cover_img)
    bg_img = media.get('bg_image') or load_bg_image(media.get('bg_image_path'))
    has_bg = bg_img is not None
    image = _prepare_dual_background(theme, bg_img)
    glass_rgb = (10, 14, 24) if has_bg else _rgb(theme['pill'])

    now = datetime.now()
    clock_str = clock or now.strftime('%H:%M')
    date_str = now.strftime('%d.%m')
    tag = (label or 'STUDIO').strip()[:8].upper()

    # Top-left: Frosted glass clock & user tag card
    _draw_glass_box(
        image, (4, 3, 79, 40), radius=10, fill_rgb=glass_rgb,
        alpha=(150 if has_bg else 205), outline_color=theme['pill_border'],
    )
    d = ImageDraw.Draw(image)
    d.text((10, 1), clock_str, font=font(20, True), fill=theme['text'])
    sub = f'{tag} · {date_str}' if tag else date_str
    d.text((11, 26), clip_text(d, sub, font(8, True), 63), font=font(8, True), fill=theme['accent'])

    # Top-right: Frosted glass CPU & RAM mini pills
    cpu_val = int(stats.get('cpu', 0))
    ram_val = int(stats.get('ram', 0))
    for _idx, (m_label, m_val, m_color, top_y) in enumerate((
        ('CPU', cpu_val, theme['accent'], 3),
        ('RAM', ram_val, theme['accent2'], 23),
    )):
        bot_y = top_y + 17
        _draw_glass_box(
            image, (83, top_y, 155, bot_y), radius=7, fill_rgb=glass_rgb,
            alpha=(155 if has_bg else 210), outline_color=theme['pill_border'],
        )
        d = ImageDraw.Draw(image)
        d.text((88, top_y + 1), m_label, font=font(8, True), fill=theme['muted'])
        val_txt = f'{m_val}%'
        vw = d.textlength(val_txt, font=font(9, True))
        d.text((int(151 - vw), top_y), val_txt, font=font(9, True), fill=m_color)
        bar_w = int(62 * max(0, min(100, m_val)) / 100)
        d.rectangle((88, bot_y - 3, 150, bot_y - 2), fill=theme['track'])
        if bar_w > 0:
            d.rectangle((88, bot_y - 3, 88 + max(2, bar_w), bot_y - 2), fill=m_color)

    # Bottom: Floating Glass One UI 7 Now Bar capsule
    available = bool(media.get('available', False))
    playing = bool(media.get('playing', False))
    pill_outline = theme['accent'] if (available and playing) or has_bg else theme['pill_border']
    _draw_glass_box(
        image, (4, 44, 155, 92), radius=16, fill_rgb=glass_rgb,
        alpha=(175 if has_bg else 220), outline_color=pill_outline,
    )
    d = ImageDraw.Draw(image)

    if available and cover_img is not None:
        _paste_rounded_cover(image, cover_img, 10, 49, 32, radius=7, border_color=theme['accent'])
        d = ImageDraw.Draw(image)
        text_x = 47
        title_w = 88 if playing else 101
        if playing:
            _draw_mini_eq(d, 138, 51, 9, theme, playing, phase=motion_phase, bars=3)
    else:
        d.rounded_rectangle((10, 50, 38, 78), radius=8, fill=theme['badge'], outline=theme['accent'], width=1)
        _draw_eq_or_icon(d, 24, 64, 13, theme, available, playing, phase=motion_phase, bars=4)
        text_x = 44
        title_w = 104

    if available:
        title_txt = media.get('title') or t('Çalan Parça')
        artist_txt = media.get('artist') or (media.get('source') or t('Medya'))
    else:
        title_txt = (custom_note or '').strip() or t('Hazır · Now Bar')
        artist_txt = f"RAM {stats.get('used', '0')}/{stats.get('total', '0')} GB · CPU {cpu_val}%"

    duration = float(media.get('duration', 0) or 0)
    position = float(media.get('position', 0) or 0)
    hide_elapsed = bool(media.get('hide_elapsed', False))
    _draw_scrolling_text(image, text_x, 46, title_w, 15, title_txt, font(11, True), theme['text'], None, phase=media.get('scroll_phase', phase))
    d = ImageDraw.Draw(image)
    if available and duration > 0:
        if hide_elapsed:
            time_txt = t('SÜRE {time}', time=_format_mmss(duration))
        else:
            time_txt = f'{_format_mmss(position)}/{_format_mmss(duration)}'
        tw = d.textlength(time_txt, font=font(8, True))
        tx = int(147 - tw)
        artist_w = max(12, tx - text_x - 4)
        _draw_scrolling_text(image, text_x, 61, artist_w, 12, artist_txt, font(9, False), theme['muted'], None, phase=None)
        d = ImageDraw.Draw(image)
        d.text((tx, 62), time_txt, font=font(8, True), fill=theme['accent'])
    else:
        _draw_scrolling_text(image, text_x, 61, 148 - text_x, 12, artist_txt, font(9, False), theme['muted'], None, phase=None)
        d = ImageDraw.Draw(image)

    # Bottom wave scrubber (when media available) or clean RAM gauge (when idle)
    if available:
        ratio = max(0.0, min(1.0, position / duration)) if duration > 0 else 0.45
        _draw_wave_scrubber(image, 14, 145, 83, ratio, theme, available=True, playing=playing, phase=motion_phase)
    else:
        d.rounded_rectangle((14, 83, 145, 86), radius=2, fill=theme['track'])
        ratio = max(0.0, min(1.0, ram_val / 100.0))
        fill_w = max(4, int(131 * ratio)) if ratio > 0 else 16
        d.rounded_rectangle((14, 83, 14 + fill_w, 86), radius=2, fill=theme['accent2'])
    return image


def render_nowbar_media(media, stats, theme_key='galaxy', label='STUDIO', custom_note='', phase=None, clock=None):
    motion_phase = media.get('motion_phase', phase)
    cover_img = get_cover_image(media)
    theme = _resolve_theme(theme_key, cover_img)
    image = Image.new('RGB', SIZE, theme['bg'])
    d = ImageDraw.Draw(image)
    clock_str = clock or datetime.now().strftime('%H:%M')
    tag = f"{(label or 'STUDIO').strip()[:8].upper()} · NOW BAR"
    _draw_top_bar(d, theme, tag, clock_str)

    available = bool(media.get('available', False))
    playing = bool(media.get('playing', False))

    # Large Media Now Bar capsule (ambient cover glow when artwork is available)
    if available and cover_img is not None:
        _ambient_pill(image, cover_img, (4, 18, 155, 92), 18, theme['pill'], theme['pill_border'])
        _paste_rounded_cover(image, cover_img, 10, 24, 42, radius=8, border_color=theme['accent'])
        text_x = 58
        text_w = 90
        if playing:
            _draw_mini_eq(d, 134, 22, 9, theme, playing, phase=motion_phase, bars=4)
    else:
        d.rounded_rectangle((4, 18, 155, 92), radius=18, fill=theme['pill'], outline=theme['pill_border'], width=1)
        # Left rounded EQ / album badge
        d.rounded_rectangle((11, 25, 45, 59), radius=10, fill=theme['badge'], outline=theme['accent'], width=1)
        _draw_eq_or_icon(d, 28, 42, 18, theme, available, playing, phase=motion_phase, bars=5)
        text_x = 52
        text_w = 96

    # Right status + scrolling title + artist
    if available:
        status_label = t('ÇALIYOR') if playing else t('DURAKLATILDI')
        title_txt = media.get('title') or t('Bilinmeyen Parça')
        artist_txt = media.get('artist') or (media.get('source') or t('Medya'))
    else:
        status_label = t('BEKLEMEDE')
        title_txt = (custom_note or '').strip() or t('Medya bekleniyor')
        artist_txt = t('Spotify veya tarayıcı aç')

    d.text((text_x, 22), status_label, font=font(8, True), fill=theme['accent'])
    _draw_scrolling_text(image, text_x, 34, text_w, 18, title_txt, font(12, True), theme['text'], None, phase=media.get('scroll_phase', phase))
    _draw_scrolling_text(image, text_x, 52, text_w, 13, artist_txt, font(9, False), theme['muted'], None, phase=None)

    # Progress wave scrubber and time stamps inside capsule
    duration = float(media.get('duration', 0) or 0)
    position = float(media.get('position', 0) or 0)
    hide_elapsed = bool(media.get('hide_elapsed', False))
    if available:
        ratio = max(0.0, min(1.0, position / duration)) if duration > 0 else 0.45
        _draw_wave_scrubber(image, 12, 147, 72, ratio, theme, available=True, playing=playing, phase=motion_phase)
        d = ImageDraw.Draw(image)
        if duration > 0:
            if hide_elapsed:
                left_status = t('ÇALIYOR') if playing else t('DURAKLATILDI')
                d.text((12, 79), left_status, font=font(8, True), fill=theme['muted'])
                end_str = t('Süre: {time}', time=_format_mmss(duration))
                ew = d.textlength(end_str, font=font(8, True))
                d.text((int(147 - ew), 79), end_str, font=font(8, True), fill=theme['accent'])
            else:
                d.text((12, 79), _format_mmss(position), font=font(8, True), fill=theme['muted'])
                end_str = _format_mmss(duration)
                ew = d.textlength(end_str, font=font(8, True))
                d.text((int(147 - ew), 79), end_str, font=font(8, True), fill=theme['muted'])
        else:
            left_status = t('ÇALIYOR') if playing else t('DURAKLATILDI')
            d.text((12, 79), left_status, font=font(8, True), fill=theme['muted'])
    else:
        # Subtle pulse bar if idle
        d.rounded_rectangle((12, 70, 147, 75), radius=2, fill=theme['track'])
        pulse_x = 12 if phase is None else 12 + int(95 * (0.5 + 0.5 * math.sin(motion_phase * 2 * math.pi)))
        d.rounded_rectangle((pulse_x, 70, min(147, pulse_x + 38), 75), radius=2, fill=theme['accent2'])
        note = (custom_note or '').strip() or f"CPU {stats.get('cpu', 0)}% · RAM {stats.get('ram', 0)}%"
        d.text((12, 77), clip_text(d, note, font(8, False), 135), font=font(8, False), fill=theme['muted'])
    return image


def render_nowbar_artwork(media, stats, theme_key='cover', label='STUDIO', custom_note='', phase=None, clock=None):
    motion_phase = media.get('motion_phase', phase)
    cover_img = get_cover_image(media)
    theme = _resolve_theme(theme_key, cover_img)
    image = Image.new('RGB', SIZE, theme['bg'])
    d = ImageDraw.Draw(image)
    now = datetime.now()
    clock_str = clock or now.strftime('%H:%M')
    tag = (label or 'STUDIO').strip()[:8].upper()
    cpu_val = int(stats.get('cpu', 0))
    ram_val = int(stats.get('ram', 0))
    _draw_top_bar(d, theme, f'{tag} · CPU {cpu_val}%  RAM {ram_val}%', now.strftime('%d.%m'))

    available = bool(media.get('available', False))
    playing = bool(media.get('playing', False))

    # Left 60x60 showcase cover or placeholder badge
    if available and cover_img is not None:
        _paste_rounded_cover(image, cover_img, 6, 17, 60, radius=10, border_color=theme['accent'])
        d = ImageDraw.Draw(image)
    else:
        d.rounded_rectangle((6, 17, 66, 77), radius=10, fill=theme['pill'], outline=theme['pill_border'], width=1)
        _draw_eq_or_icon(d, 36, 47, 24, theme, available, playing, phase=motion_phase, bars=5)

    # Right column: clock, status + time, scrolling title, artist
    d.text((73, 14), clock_str, font=font(17, True), fill=theme['text'])
    duration = float(media.get('duration', 0) or 0)
    position = float(media.get('position', 0) or 0)
    hide_elapsed = bool(media.get('hide_elapsed', False))

    if available:
        status_txt = t('ÇALIYOR') if playing else t('DURAKLAT')
        title_txt = media.get('title') or t('Bilinmeyen Parça')
        artist_txt = media.get('artist') or (media.get('source') or t('Medya'))
    else:
        status_txt = t('HAZIR')
        title_txt = (custom_note or '').strip() or t('Medya bekleniyor')
        artist_txt = f"RAM {stats.get('used', '0')}/{stats.get('total', '0')} GB"

    d.text((73, 36), status_txt, font=font(8, True), fill=theme['accent'])
    if available and duration > 0:
        t_badge = _format_mmss(duration) if hide_elapsed else _format_mmss(position)
        bw = d.textlength(t_badge, font=font(8, True))
        d.text((int(154 - bw), 36), t_badge, font=font(8, True), fill=theme['muted'])
    elif playing:
        _draw_mini_eq(d, 141, 36, 8, theme, playing, phase=motion_phase, bars=3)

    _draw_scrolling_text(image, 73, 47, 81, 15, title_txt, font(11, True), theme['text'], None, phase=media.get('scroll_phase', phase))
    _draw_scrolling_text(image, 73, 62, 81, 13, artist_txt, font(9, False), theme['muted'], None, phase=None)
    d = ImageDraw.Draw(image)

    # Full-width sleek bottom wave scrubber (media) or RAM bar (idle)
    if available:
        ratio = max(0.0, min(1.0, position / duration)) if duration > 0 else 0.45
        _draw_wave_scrubber(image, 8, 151, 86, ratio, theme, available=True, playing=playing, phase=motion_phase)
    else:
        d.rounded_rectangle((8, 86, 151, 89), radius=2, fill=theme['track'])
        fill_w = max(12, int(143 * max(0.0, min(1.0, ram_val / 100.0))))
        d.rounded_rectangle((8, 86, 8 + fill_w, 89), radius=2, fill=theme['accent2'])
    return image


def render_nowbar_system(media, stats, theme_key='galaxy', label='STUDIO', custom_note='', phase=None, clock=None):
    cover_img = get_cover_image(media)
    theme = _resolve_theme(theme_key, cover_img)
    image = Image.new('RGB', SIZE, theme['bg'])
    d = ImageDraw.Draw(image)
    now = datetime.now()
    right_txt = f"{now.strftime('%d.%m')}  {clock or now.strftime('%H:%M')}"
    tag = f"{(label or 'STUDIO').strip()[:8].upper()} · {t('SİSTEM')}"
    _draw_top_bar(d, theme, tag, right_txt)

    cpu_val = int(stats.get('cpu', 0))
    ram_val = int(stats.get('ram', 0))
    rows = (
        (19, t('İŞLEMCİ (CPU)'), cpu_val, theme['accent'], _draw_cpu_icon),
        (57, f"RAM · {stats.get('used', '0')}/{stats.get('total', '0')} GB", ram_val, theme['accent2'], _draw_ram_icon),
    )
    for idx, (top_y, title_txt, pct, color, icon_fn) in enumerate(rows):
        bot_y = top_y + 34
        d.rounded_rectangle((4, top_y, 155, bot_y), radius=14, fill=theme['pill'], outline=theme['pill_border'], width=1)
        d.ellipse((10, top_y + 6, 32, top_y + 28), fill=theme['badge'], outline=color, width=1)
        icon_fn(d, 21, top_y + 17, color)

        d.text((38, top_y + 4), clip_text(d, title_txt, font(8, True), 76), font=font(8, True), fill=theme['muted'])
        pct_txt = f'{pct}%'
        pw = d.textlength(pct_txt, font=font(11, True))
        d.text((int(147 - pw), top_y + 1), pct_txt, font=font(11, True), fill=color)

        bar_y1 = top_y + 20
        bar_y2 = top_y + 26
        d.rounded_rectangle((38, bar_y1, 146, bar_y2), radius=3, fill=theme['track'])
        fill_w = int(108 * max(0, min(100, pct)) / 100)
        if fill_w > 0:
            d.rounded_rectangle((38, bar_y1, 38 + max(4, fill_w), bar_y2), radius=3, fill=color)
        if phase is not None:
            sweep_x = 38 + int(((phase + idx * 0.35) % 1.0) * 102)
            d.ellipse((sweep_x - 2, bar_y1, sweep_x + 2, bar_y2), fill=theme['text'])
    return image


def _slide_compose(img_a, img_b, progress):
    """Horizontally slide img_a out to the left and img_b in from the right."""
    offset = int(round(SIZE[0] * progress))
    canvas = Image.new('RGB', SIZE, '#000000')
    if offset < SIZE[0]:
        canvas.paste(img_a, (-offset, 0))
    if offset > 0:
        canvas.paste(img_b, (SIZE[0] - offset, 0))
    return canvas


def render_nowbar(layout, media, stats, theme_key='galaxy', label='STUDIO', custom_note='', phase=None, clock=None):
    """Render a single 160x96 Now Bar frame for the selected layout."""
    if layout == 'nowbar_artwork':
        return render_nowbar_artwork(media, stats, theme_key, label, custom_note, phase=phase, clock=clock)
    if layout == 'nowbar_media':
        return render_nowbar_media(media, stats, theme_key, label, custom_note, phase=phase, clock=clock)
    if layout == 'nowbar_system':
        return render_nowbar_system(media, stats, theme_key, label, custom_note, phase=phase, clock=clock)
    if layout == 'nowbar_carousel':
        def panel_media(local_phase):
            if 'scroll_phase' not in media:
                return media
            return {**media, 'scroll_phase': max(0.0, min(
                0.999999, (local_phase - 0.10) / 0.80))}
        if phase is None:
            return render_nowbar_dual(media, stats, theme_key, label, custom_note, phase=None, clock=clock)
        if phase < 0.45:
            local_phase = phase / 0.45
            return render_nowbar_media(panel_media(local_phase), stats, theme_key, label, custom_note, phase=local_phase, clock=clock)
        if phase < 0.55:
            a = render_nowbar_media(panel_media(1.0), stats, theme_key, label, custom_note, phase=1.0, clock=clock)
            b = render_nowbar_system(media, stats, theme_key, label, custom_note, phase=0.0, clock=clock)
            return _slide_compose(a, b, (phase - 0.45) / 0.10)
        if phase < 0.92:
            return render_nowbar_system(media, stats, theme_key, label, custom_note, phase=((phase - 0.55) / 0.37), clock=clock)
        a = render_nowbar_system(media, stats, theme_key, label, custom_note, phase=1.0, clock=clock)
        b = render_nowbar_media(panel_media(0.0), stats, theme_key, label, custom_note, phase=0.0, clock=clock)
        return _slide_compose(a, b, (phase - 0.92) / 0.08)
    return render_nowbar_dual(media, stats, theme_key, label, custom_note, phase=phase, clock=clock)


def render_nowbar_frames(
    layout,
    media,
    stats,
    theme_key='galaxy',
    label='STUDIO',
    custom_note='',
    animated=False,
    frame_count=20,
    mode=None,
    clock=None,
):
    """Return (frames, durations_ms) ready for RGB565 USB upload or GIF export."""
    media = media or {}
    stats = stats or {}
    active_mode = mode if mode is not None else ('animated' if animated else 'static')
    if active_mode == 'static':
        image = render_nowbar(layout, media, stats, theme_key, label, custom_note, phase=None, clock=clock)
        return [image], [100]

    count = max(2, min(255, int(frame_count)))
    background = (load_bg_animation(media.get('bg_image_path'))
                  if layout == 'nowbar_dual' and media.get('bg_image') is None else None)
    if active_mode == 'device_loop':
        # All motion is precompiled into ONE normal animation upload. No timer
        # or per-frame USB writes run while the keyboard replays this loop.
        title = ((media.get('title') or '') if media.get('available')
                 else (custom_note or t('Hazır · Now Bar')))
        draw = ImageDraw.Draw(Image.new('RGB', (1, 1)))
        if background and len(background['frames']) > 1 and not media.get('available'):
            starts = background['starts']
            holds = [end - start for start, end in zip(
                starts, starts[1:] + [background['duration']])]
            if (draw.textlength(title, font=font(11, True)) <= 104
                    and all(30 <= hold <= 500 for hold in holds)):
                # An idle card adds no moving widgets. Keep the original GIF
                # cycle instead of uploading redundant repeats of its frames.
                frames = [render_nowbar(layout, {**media, 'bg_image': bg}, stats,
                          theme_key, label, custom_note, phase=None, clock=clock)
                          for bg in background['frames']]
                return frames, [round(hold / 2) * 2 for hold in holds]
        title_width = draw.textlength(title + '   •   ', font=font(12, True))
        period = max(4000, min(12000, (title_width / 32.0 + 0.8) * 1000))
        if layout == 'nowbar_carousel':
            period = max(8000, period)
        repeats = 1
        if background and len(background['frames']) > 1:
            # Complete wallpaper cycles avoid a cut at the loop boundary.
            # This mode has a 96-frame/500ms budget. Sources longer than 48s
            # are time-compressed; the separate GIF tool has a 255-frame cap.
            bg_period = background['duration']
            repeats = max(1, math.ceil(period / bg_period))
            period = min(48000, bg_period * repeats)
        cap = max(48, min(96, int(frame_count)))
        count = max(48, min(cap, math.ceil(period / 80.0)))
        delay = max(30, min(500, round(period / count / 2) * 2))
        motion_cycles = max(1, round(count * delay / 1200))
        frames = []
        for i in range(count):
            phase = i / count
            frame_media = {
                **media,
                'hide_elapsed': True,
                'motion_phase': (phase * motion_cycles) % 1.0,
                # Rest at the start of a long title before scrolling it.
                'scroll_phase': max(0.0, min(0.999999, (phase - 0.10) / 0.80)),
            }
            if background:
                frame_media['bg_image'] = background_at(
                    background, phase * background['duration'] * repeats)
            frames.append(render_nowbar(layout, frame_media, stats, theme_key,
                                        label, custom_note, phase=phase, clock=clock))
        return frames, [delay] * count

    if active_mode == 'timeline':
        delay = 500
        now = datetime.now()
        frames = []
        for i in range(count):
            dt_sec = i * (delay / 1000.0)
            frame_media = dict(media)
            if frame_media.get('available') and frame_media.get('playing'):
                pos = float(frame_media.get('position', 0.0) or 0.0) + dt_sec
                dur = float(frame_media.get('duration', 0.0) or 0.0)
                if dur > 0:
                    pos = min(dur, pos)
                frame_media['position'] = pos
            frame_clock = (now + timedelta(seconds=dt_sec)).strftime('%H:%M')
            frames.append(
                render_nowbar(
                    layout, frame_media, stats, theme_key, label, custom_note,
                    phase=(i / count), clock=frame_clock,
                )
            )
        return frames, [delay] * len(frames)

    delay = 120
    if layout == 'nowbar_carousel' and count >= 8:
        frames = []
        trans = 2 if count >= 12 else 1
        media_n = (count - 2 * trans) // 2
        sys_n = count - 2 * trans - media_n
        for i in range(media_n):
            frames.append(render_nowbar_media(media, stats, theme_key, label, custom_note, phase=i / max(1, media_n), clock=clock))
        end_m = render_nowbar_media(media, stats, theme_key, label, custom_note, phase=1.0, clock=clock)
        start_s = render_nowbar_system(media, stats, theme_key, label, custom_note, phase=0.0, clock=clock)
        for step in range(1, trans + 1):
            frames.append(_slide_compose(end_m, start_s, step / (trans + 1)))
        for i in range(sys_n):
            frames.append(render_nowbar_system(media, stats, theme_key, label, custom_note, phase=i / max(1, sys_n), clock=clock))
        end_s = render_nowbar_system(media, stats, theme_key, label, custom_note, phase=1.0, clock=clock)
        start_m = render_nowbar_media(media, stats, theme_key, label, custom_note, phase=0.0, clock=clock)
        for step in range(1, trans + 1):
            frames.append(_slide_compose(end_s, start_m, step / (trans + 1)))
        return frames, [delay] * len(frames)

    frames = []
    for i in range(count):
        frame_media = media
        if background:
            frame_media = {**media, 'bg_image': background_at(
                background, i * background['duration'] / count)}
        frames.append(render_nowbar(layout, frame_media, stats, theme_key, label,
                                    custom_note, phase=i / count, clock=clock))
    return frames, [delay] * len(frames)


# ---------------------------------------------------------------------------
# Legacy helpers preserved for compatibility
# ---------------------------------------------------------------------------

def music_icon(draw, x, y, color):
    draw.line((x + 4, y + 2, x + 4, y + 10), fill=color, width=2)
    draw.line((x + 4, y + 2, x + 10, y + 1, x + 10, y + 9), fill=color, width=2)
    draw.ellipse((x, y + 8, x + 5, y + 12), fill=color)
    draw.ellipse((x + 6, y + 7, x + 11, y + 11), fill=color)


def system_icon(draw, x, y, color):
    draw.rounded_rectangle((x, y + 1, x + 12, y + 10), radius=2, outline=color)
    draw.line((x + 6, y + 10, x + 6, y + 13), fill=color)
    draw.line((x + 2, y + 13, x + 10, y + 13), fill=color)


def bell_icon(draw, x, y, color):
    draw.arc((x + 2, y + 1, x + 11, y + 12), 180, 360, fill=color, width=2)
    draw.line((x + 2, y + 6, x + 1, y + 10, x + 12, y + 10, x + 11, y + 6), fill=color, width=1)
    draw.ellipse((x + 5, y + 12, x + 8, y + 14), fill=color)


def base(page, clock=None):
    image = Image.new('RGB', (160, 96), BG)
    d = ImageDraw.Draw(image)
    accent = ACCENTS[page]
    d.text((7, 1), 'STUDIO', font=font(8, True), fill=MUTED)
    d.text((47, 1), t({'spotify': 'MÜZİK', 'system': 'SİSTEM', 'notification': 'BİLDİRİM'}[page]), font=font(8, True), fill=accent)
    d.text((123, 1), clock or datetime.now().strftime('%H:%M'), font=font(8), fill=TEXT)
    d.line((7, 14, 152, 14), fill='#283348')
    for index, (key, label, icon) in enumerate((('spotify', 'Müzik', music_icon), ('system', 'Sistem', system_icon), ('notification', 'Uyarı', bell_icon))):
        x = 3 + index * 52
        selected = key == page
        d.rounded_rectangle((x, 79, x + 49, 94), radius=4, fill=PANEL if selected else BG)
        color = accent if selected else '#63728a'
        icon(d, x + 4, 80, color)
        d.text((x + 20, 81), clip_text(d, t(label), font(8, selected), 28), font=font(8, selected), fill=color)
        if selected:
            d.line((x + 9, 95, x + 40, 95), fill=accent, width=1)
    return image, d


def lines(draw, text, typeface, width, max_lines=2):
    words = str(text).split()
    result = []
    current = ''
    for word in words:
        candidate = (current + ' ' + word).strip()
        if draw.textlength(candidate, font=typeface) > width and current:
            result.append(current)
            current = word
            if len(result) == max_lines - 1:
                break
        else:
            current = candidate
    if len(result) < max_lines:
        result.append(current)
    if len(result) == max_lines and words:
        consumed = len(' '.join(result[:-1]).split())
        result[-1] = clip_text(draw, ' '.join(words[consumed:]), typeface, width)
    return [clip_text(draw, line, typeface, width) for line in result]


def render_spotify(info, clock=None):
    image, d = base('spotify', clock)
    a = ACCENTS['spotify']
    playing = info.get('playing', False)
    d.rounded_rectangle((7, 21, 27, 41), radius=6, fill='#123828')
    if playing:
        d.polygon(((14, 26), (14, 36), (22, 31)), fill=a)
    else:
        d.rectangle((13, 26, 15, 36), fill=a)
        d.rectangle((20, 26, 22, 36), fill=a)
    d.text((34, 20), t('ÇALIYOR') if playing else t('DURAKLATILDI'), font=font(8, True), fill=a)
    title = info.get('title') or t('Spotify hazır')
    d.text((7, 43), clip_text(d, title, font(12, True), 146), font=font(12, True), fill=TEXT)
    d.text((7, 61), clip_text(d, info.get('artist') or t('Bir şarkı aç'), font(9), 146), font=font(9), fill=MUTED)
    return image


def render_system(stats, clock=None):
    image, d = base('system', clock)
    a = ACCENTS['system']
    for y, label, value in ((23, 'CPU', stats.get('cpu', 0)), (46, 'RAM', stats.get('ram', 0))):
        d.text((8, y), label, font=font(9, True), fill=MUTED)
        d.text((57, y), f'{int(value):2d}%', font=font(10, True), fill=TEXT)
        d.rounded_rectangle((94, y + 5, 151, y + 9), radius=2, fill=PANEL)
        if value > 0:
            d.rounded_rectangle((94, y + 5, 94 + max(2, int(57 * min(100, value) / 100)), y + 9), radius=2, fill=a)
    d.text((8, 66), datetime.now().strftime('%d.%m') + '  /  ' + str(stats.get('used', '')) + ' GB', font=font(8), fill='#62738d')
    return image


def render_notification(notification, clock=None):
    image, d = base('notification', clock)
    a = ACCENTS['notification']
    d.text((8, 20), clip_text(d, notification.get('app') or t('Bildirim'), font(8, True), 144), font=font(8, True), fill=a)
    text = notification.get('title') or t('Yeni bildirim')
    d.text((8, 35), clip_text(d, text, font(11, True), 144), font=font(11, True), fill=TEXT)
    for i, line in enumerate(lines(d, notification.get('body', ''), font(9), 144, 2)):
        d.text((8, 52 + 11 * i), line, font=font(9), fill=MUTED)
    return image


def render(page, media, stats, notification=None):
    if page == 'spotify':
        return render_spotify(media)
    if page == 'notification':
        return render_notification(notification or {'app': t('Bildirimler'), 'title': t('Her şey sakin'), 'body': t('Yeni bildirimler burada görünecek.')})
    return render_system(stats)


class Router:
    def __init__(self):
        self.override = 'auto'
        self.notification = None
        self.until = 0.0

    def push(self, notification, now=None):
        self.notification = notification
        self.until = (time.monotonic() if now is None else now) + 10

    def page(self, media, now=None):
        if self.notification and (time.monotonic() if now is None else now) < self.until:
            return 'notification'
        if self.override != 'auto':
            return self.override
        return 'spotify' if media.get('available', False) else 'system'
