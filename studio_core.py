"""KB884L local media preparation. This module never writes USB reports."""
from __future__ import annotations
import asyncio
import bisect
import ctypes
from ctypes import wintypes
from contextlib import closing
from datetime import datetime, timezone
from functools import lru_cache
import hashlib
import io
import json
import os
from pathlib import Path
import sqlite3
import sys
import threading
import urllib.parse
import urllib.request
import uuid
import winreg
import psutil
from i18n import t
import i18n_backend
from PIL import Image, ImageDraw, ImageFont, ImageOps

SIZE = (160, 96)
MAX_FRAMES = 255  # Verified in the installed DeviceDriver.exe upload routine.

# Prime psutil CPU measurement so the first non-blocking call reflects real activity.
psutil.cpu_percent(interval=None)

_COVER_BY_HASH: dict[str, Image.Image] = {}
_TRACK_COVER_CACHE: dict[tuple[str, str, str], str] = {}
_BG_CACHE: dict[tuple[str, int], Image.Image] = {}
_BG_ANIMATION_CACHE: dict[tuple[str, int, int], dict] = {}
_RUN_REG_PATH = r'Software\Microsoft\Windows\CurrentVersion\Run'
_RUN_REG_NAME = 'KB884LNowBarStudio'


def app_dir():
    """Return directory containing the executable (when frozen) or source script."""
    if getattr(sys, 'frozen', False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def settings_path():
    return app_dir() / 'studio_settings.json'


def load_settings():
    p = settings_path()
    if not p.is_file():
        return {}
    try:
        data = json.loads(p.read_text(encoding='utf-8-sig'))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def save_settings(data):
    p = settings_path()
    try:
        tmp = p.with_suffix('.tmp')
        tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding='utf-8')
        tmp.replace(p)
    except Exception:
        pass


def default_startup_command():
    exe_path = app_dir() / 'KB884L-Studio.exe'
    if exe_path.is_file():
        return f'"{exe_path}" --background'
    if getattr(sys, 'frozen', False):
        return f'"{Path(sys.executable).resolve()}" --background'
    script_path = app_dir() / 'studio.py'
    return f'"{Path(sys.executable).resolve()}" "{script_path}" --background'


def get_windows_startup():
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_REG_PATH, 0, winreg.KEY_READ) as key:
            val, _ = winreg.QueryValueEx(key, _RUN_REG_NAME)
            return bool(val)
    except OSError:
        return False


def set_windows_startup(enabled, target_cmd=None):
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_REG_PATH, 0, winreg.KEY_SET_VALUE) as key:
            if enabled:
                cmd = target_cmd or default_startup_command()
                winreg.SetValueEx(key, _RUN_REG_NAME, 0, winreg.REG_SZ, cmd)
            else:
                try:
                    winreg.DeleteValue(key, _RUN_REG_NAME)
                except FileNotFoundError:
                    pass
        return True
    except OSError:
        return False


def load_bg_image(path_str):
    """Load, crop-fit to 160x96, and cache a custom background wallpaper image."""
    if not path_str:
        return None
    try:
        p = Path(path_str)
        if not p.is_file():
            return None
        mtime = p.stat().st_mtime_ns
        key = (str(p), mtime)
        cached = _BG_CACHE.get(key)
        if cached is not None:
            return cached
        with Image.open(p) as im:
            rgb = im.convert('RGB')
            fitted = ImageOps.fit(rgb, SIZE, method=Image.Resampling.LANCZOS)
        if len(_BG_CACHE) > 12:
            _BG_CACHE.clear()
        _BG_CACHE[key] = fitted
        return fitted
    except Exception:
        return None


def load_bg_animation(path_str):
    """Decode a bounded wallpaper timeline, retaining GIF disposal and timing.

    Frames are fitted once and cached. Sampling is by elapsed time, so a long
    held frame stays visible rather than receiving the same weight as a flash.
    This is local preparation only; it never communicates with the keyboard.
    """
    if not path_str:
        return None
    try:
        path = Path(path_str)
        stat = path.stat()
        key = (str(path), stat.st_mtime_ns, stat.st_size)
        cached = _BG_ANIMATION_CACHE.get(key)
        if cached is not None:
            return cached
        with Image.open(path) as source:
            count = getattr(source, 'n_frames', 1)
            if count > 2000 or source.width * source.height * count > 256_000_000:
                return None
            starts, total = [], 0
            for index in range(count):
                source.seek(index)
                starts.append(total)
                total += max(10, int(source.info.get('duration', 100) or 100))
            target_count = min(count, 96)
            if count <= target_count:
                indices, times = list(range(count)), starts
            else:
                times = [round(i * total / target_count) for i in range(target_count)]
                indices = [max(0, bisect.bisect_right(starts, tick) - 1) for tick in times]
            frames = []
            for index in indices:
                source.seek(index)
                rgba = source.convert('RGBA')
                background = Image.new('RGBA', rgba.size, (0, 0, 0, 255))
                background.alpha_composite(rgba)
                frames.append(ImageOps.fit(background.convert('RGB'), SIZE,
                                           method=Image.Resampling.LANCZOS))
        result = {'frames': frames, 'starts': times, 'duration': total}
        # A small cache avoids retaining many decoded wallpapers in the tray app.
        if len(_BG_ANIMATION_CACHE) >= 3:
            _BG_ANIMATION_CACHE.pop(next(iter(_BG_ANIMATION_CACHE)))
        _BG_ANIMATION_CACHE[key] = result
        return result
    except (OSError, ValueError, EOFError, Image.DecompressionBombError):
        return None


def background_at(animation, elapsed_ms):
    """Return the wallpaper frame active at elapsed_ms, wrapping at its end."""
    if not animation or not animation.get('frames'):
        return None
    tick = float(elapsed_ms) % max(1, animation['duration'])
    index = max(0, bisect.bisect_right(animation['starts'], tick) - 1)
    return animation['frames'][index]


def register_cover_image(image):
    """Store a resized copy of a PIL cover image in cache and return its short hash."""
    if image is None:
        return ''
    rgb = image.convert('RGB')
    thumb = rgb.copy()
    thumb.thumbnail((128, 128), Image.Resampling.LANCZOS)
    key = hashlib.md5(thumb.resize((16, 16)).tobytes()).hexdigest()[:10]
    _COVER_BY_HASH[key] = thumb
    if len(_COVER_BY_HASH) > 64:
        oldest = next(iter(_COVER_BY_HASH))
        if oldest != key:
            _COVER_BY_HASH.pop(oldest, None)
    return key


def get_cover_image(media):
    """Return cached PIL cover Image for a media_info() dictionary, if available."""
    if not isinstance(media, dict):
        return None
    direct = media.get('cover')
    if direct is not None:
        return direct
    return _COVER_BY_HASH.get(media.get('cover_hash') or '')


async def _read_smtc_thumbnail(thumb_ref):
    if thumb_ref is None:
        return None
    try:
        from winrt.windows.storage.streams import DataReader
        stream = await thumb_ref.open_read_async()
        size = int(stream.size)
        if not (0 < size <= 10_000_000):
            return None
        reader = DataReader(stream)
        await reader.load_async(size)
        buf = bytearray(size)
        reader.read_bytes(buf)
        with Image.open(io.BytesIO(bytes(buf))) as img:
            return img.convert('RGB')
    except Exception:
        return None


def _fetch_itunes_cover(title, artist='', source_short=''):
    """Query Apple iTunes Search API as an online fallback for song album art."""
    clean_title = (title or '').strip()
    if not clean_title or clean_title.lower() in ('medya bekleniyor', 'bilinmeyen parça', 'waiting for media', 'unknown track'):
        return None
    clean_artist = (artist or '').strip()
    if clean_artist.lower() == (source_short or '').strip().lower():
        clean_artist = ''
    query = f'{clean_artist} {clean_title}'.strip()
    url = f'https://itunes.apple.com/search?term={urllib.parse.quote(query)}&entity=song&limit=1'
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'KB884L-NowBar-Studio/2.0'})
        with urllib.request.urlopen(req, timeout=2.5) as resp:
            payload = json.loads(resp.read().decode('utf-8'))
        results = payload.get('results') or []
        if not results:
            return None
        art_url = results[0].get('artworkUrl100') or results[0].get('artworkUrl60')
        if not art_url:
            return None
        art_req = urllib.request.Request(art_url, headers={'User-Agent': 'KB884L-NowBar-Studio/2.0'})
        with urllib.request.urlopen(art_req, timeout=2.5) as img_resp:
            with Image.open(io.BytesIO(img_resp.read())) as img:
                return img.convert('RGB')
    except Exception:
        return None

def driver_root():
    # SHGetFolderPath handles relocated Windows Documents folders.
    buffer = ctypes.create_unicode_buffer(32768)
    result = ctypes.windll.shell32.SHGetFolderPathW(None, 5, None, 0, buffer)
    if result:
        raise OSError(t('Windows Belgeler klasörü bulunamadı.'))
    return Path(buffer.value) / 'KB884L Gaming Keyboard Driver Files'

def prepare_gif(path, fit='contain'):
    """Composite GIF disposal correctly, then sample over the entire timeline."""
    path = Path(path)
    frames, durations = [], []
    with Image.open(path) as source:
        if source.format != 'GIF':
            raise ValueError(t('Lütfen gerçek bir .gif dosyası seç.'))
        count = getattr(source, 'n_frames', 1)
        if count > 20000 or source.width * source.height > 16000000:
            raise ValueError(t('Bu GIF çok büyük. Daha küçük bir GIF seç.'))
        original_size = source.size
        times = []
        total = 0
        for index in range(count):
            source.seek(index)
            delay = max(10, int(source.info.get('duration', 100) or 100))
            times.append(total)
            total += delay
        target_count = min(count, MAX_FRAMES)
        if count <= MAX_FRAMES:
            selected = list(range(count))
            selected_delays = []
            for index in selected:
                end = times[index+1] if index+1 < count else total
                selected_delays.append(end-times[index])
        else:
            selected = [min(count-1, bisect.bisect_right(times, i*total/target_count)-1)
                        for i in range(target_count)]
            selected_delays = [round((i+1)*total/target_count)-round(i*total/target_count)
                               for i in range(target_count)]
        # GIF seeking in ascending order makes Pillow apply frame disposal and deltas.
        for index, delay in zip(selected, selected_delays):
            source.seek(index)
            rgba = source.convert('RGBA')
            background = Image.new('RGBA', rgba.size, (0,0,0,255))
            background.alpha_composite(rgba)
            image = background.convert('RGB')
            if fit == 'cover':
                image = ImageOps.fit(image, SIZE, method=Image.Resampling.LANCZOS)
            else:
                image = ImageOps.pad(image, SIZE, method=Image.Resampling.LANCZOS, color='black')
            frames.append(image)
            # Vendor UI supports 30–500ms; RGB565 upload uses delay/2 ticks.
            durations.append(min(500, max(30, round(delay/10)*10)))
    return {'name': path.stem, 'frames': frames, 'durations': durations,
            'source_frames': count, 'source_size': original_size, 'source_duration': total,
            'duration': sum(durations)}

def save_gif(media, path):
    frames = media['frames']
    frames[0].save(path, format='GIF', save_all=True, append_images=frames[1:],
                   duration=media['durations'], loop=0, disposal=2, optimize=False)

def add_to_driver(media, root=None):
    """Append a new item to the vendor's existing schema, with an SQLite backup."""
    if not 1 <= len(media['frames']) <= MAX_FRAMES:
        raise ValueError(t('Kare sayısı 1–255 arasında olmalı.'))
    root = Path(root) if root else driver_root()
    database = root/'db/RKGK890_data.db'
    if not database.is_file():
        raise FileNotFoundError(t('HAVIT kütüphanesi bulunamadı. Önce KB884L yazılımını bir kez aç.'))
    stamp = datetime.now().strftime('%Y%m%d%H%M%S%f')
    folder_name = 'Studio_' + stamp + '_' + uuid.uuid4().hex[:6]
    folder = root/'led'/folder_name
    folder.mkdir(parents=True)
    for i, frame in enumerate(media['frames']):
        frame.convert('RGB').save(folder/f'{i}.png')
    backup_dir = root/'Studio Backups'
    backup_dir.mkdir(exist_ok=True)
    backup_path = backup_dir/f'RKGK890_{stamp}.db'
    with closing(sqlite3.connect(database, timeout=10)) as connection:
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if not {'t_ledlayer_data','t_ledframe_data','t_keyprofile'} <= tables:
            raise ValueError(t('HAVIT veritabanı biçimi farklı. Hiçbir kayıt değiştirilmedi.'))
        with closing(sqlite3.connect(backup_path)) as backup:
            connection.backup(backup)
        connection.execute('BEGIN IMMEDIATE')
        row = connection.execute('SELECT profile FROM t_ledlayer_data ORDER BY led_id LIMIT 1').fetchone()
        if row is None:
            row = connection.execute('SELECT profile_id FROM t_keyprofile ORDER BY profile_id LIMIT 1').fetchone()
        if row is None:
            raise ValueError(t('HAVIT profilini bulamadım. Önce yazılımda bir profil oluştur.'))
        cursor = connection.execute(
            'INSERT INTO t_ledlayer_data(profile,type,name,frame_size,file_dir,first_file) VALUES(?,?,?,?,?,?)',
            (row[0],0,media['name'][:100],len(media['frames']),folder_name,'0.png'))
        led_id=cursor.lastrowid
        connection.executemany(
            'INSERT INTO t_ledframe_data(led_id,name,delay_time,frame_index,file_name) VALUES(?,?,?,?,?)',
            [(led_id,f'{i}.png',int(delay),i,f'{i}.png') for i,delay in enumerate(media['durations'])])
        connection.commit()
    return {'led_id':led_id,'backup':str(backup_path),'folder':str(folder)}

def _media_source_label(source_id):
    """Shorten either a Win32 executable name or a packaged app's AUMID."""
    source_id = str(source_id or '').strip()
    package, separator, application = source_id.partition('!')
    name = application if separator and application else package
    if separator and name.lower() in ('app', 'application'):
        name = package.split('_', 1)[0]
    name = name.replace('\\', '/').rsplit('/', 1)[-1]
    if name.lower().endswith('.exe'):
        return name[:-4]
    return name.rsplit('.', 1)[-1]


async def media_info():
    idle = {
        'available': False,
        'playing': False,
        'title': t('Medya bekleniyor'),
        'artist': t('Spotify veya tarayıcıda oynat'),
        'position': 0.0,
        'duration': 0.0,
        'source': '',
        'has_cover': False,
        'cover_hash': '',
    }
    try:
        from winrt.windows.media.control import GlobalSystemMediaTransportControlsSessionManager
        manager = await GlobalSystemMediaTransportControlsSessionManager.request_async()
        sessions = list(manager.get_sessions())
        if not sessions:
            return idle

        def _is_playing(session):
            try:
                return int(session.get_playback_info().playback_status) == 4
            except Exception:
                return False

        def _source_name(session):
            return (session.source_app_user_model_id or '').lower()

        spotify_sessions = [s for s in sessions if 'spotify' in _source_name(s)]
        playing_sessions = [s for s in sessions if _is_playing(s)]

        current_session = manager.get_current_session()
        target = None
        properties = None
        seen = set()
        for pool in (
            [s for s in spotify_sessions if _is_playing(s)],
            playing_sessions,
            spotify_sessions,
            [current_session] if current_session else [],
            sessions,
        ):
            for candidate in pool:
                candidate_id = id(candidate)
                if candidate_id in seen:
                    continue
                seen.add(candidate_id)
                try:
                    props = await candidate.try_get_media_properties_async()
                except Exception:
                    # A session can close between enumeration and this read.
                    continue
                if props is not None and (props.title or '').strip():
                    target = candidate
                    properties = props
                    break
            if target is not None:
                break

        if target is None:
            return idle

        playing = _is_playing(target)
        timeline = target.get_timeline_properties()
        start_sec = timeline.start_time.total_seconds()
        end_sec = timeline.end_time.total_seconds()
        pos_sec = timeline.position.total_seconds()
        duration = max(0.0, float(end_sec - start_sec))
        position = max(0.0, float(pos_sec - start_sec))
        if playing:
            try:
                last_up = timeline.last_updated_time
                if last_up is not None and last_up.year > 1970:
                    elapsed = (datetime.now(timezone.utc) - last_up).total_seconds()
                    if 0.0 < elapsed < 36000.0:
                        position += elapsed
            except Exception:
                pass
        if duration > 0:
            position = min(duration, position)

        source_raw = target.source_app_user_model_id or ''
        source_short = _media_source_label(source_raw)
        title_str = (properties.title or t('Bilinmeyen parça')).strip()
        artist_str = (properties.artist or source_short or '').strip()

        cache_key = (title_str.lower(), artist_str.lower(), source_short.lower())
        cover_hash = _TRACK_COVER_CACHE.get(cache_key)
        if cover_hash is None:
            cover_img = await _read_smtc_thumbnail(getattr(properties, 'thumbnail', None))
            if cover_img is None:
                cover_img = _fetch_itunes_cover(title_str, artist_str, source_short)
            cover_hash = register_cover_image(cover_img) if cover_img is not None else ''
            _TRACK_COVER_CACHE[cache_key] = cover_hash
            if len(_TRACK_COVER_CACHE) > 64:
                _TRACK_COVER_CACHE.pop(next(iter(_TRACK_COVER_CACHE)), None)

        return {
            'available': True,
            'playing': playing,
            'title': title_str,
            'artist': artist_str,
            'position': position,
            'duration': duration,
            'source': source_short,
            'has_cover': bool(cover_hash),
            'cover_hash': cover_hash,
        }
    except Exception:
        return idle

@lru_cache(maxsize=64)
def font(size, bold=False):
    name='segoeuib.ttf' if bold else 'segoeui.ttf'
    return ImageFont.truetype(str(Path(os.environ.get('WINDIR',r'C:\Windows'))/'Fonts'/name),size)

def clip_text(draw, text, typeface, width):
    text=str(text)
    if draw.textlength(text,font=typeface)<=width:
        return text
    while text and draw.textlength(text+'…',font=typeface)>width:
        text=text[:-1]
    return text+'…'

def spotify_card(info):
    image=Image.new('RGB',SIZE,'#08140f')
    draw=ImageDraw.Draw(image)
    draw.rounded_rectangle((7,7,30,30),radius=7,fill='#1ed760')
    for offset in (0,4,8):
        draw.arc((11,12+offset,27,22+offset),start=205,end=335,fill='#072011',width=2)
    draw.text((37,9),'SPOTIFY',font=font(10,True),fill='#5de393')
    draw.text((8,36),clip_text(draw,info['title'],font(13,True),144),font=font(13,True),fill='white')
    draw.text((8,56),clip_text(draw,info['artist'],font(10),144),font=font(10),fill='#a6bcaf')
    draw.rounded_rectangle((8,78,151,81),radius=1,fill='#294438')
    ratio = min(1,max(0,info.get('position',0)/max(1,info.get('duration',1))))
    if ratio>0:
        draw.rectangle((8,78,8+int(143*ratio),81),fill='#1ed760')
    return image

class MemoryStatus(ctypes.Structure):
    _fields_=[('length',wintypes.DWORD),('load',wintypes.DWORD)]+[(name,ctypes.c_ulonglong) for name in
        ('total_phys','avail_phys','total_page','avail_page','total_virtual','avail_virtual','avail_extended')]

def memory_info():
    memory=MemoryStatus(); memory.length=ctypes.sizeof(memory)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(memory)):
        raise ctypes.WinError()
    return memory.load, (memory.total_phys-memory.avail_phys)/2**30, memory.total_phys/2**30

def system_stats():
    """Return current CPU %, RAM %, used GB and total GB strings."""
    load, used, total = memory_info()
    cpu = psutil.cpu_percent(interval=None)
    return {
        'cpu': max(0, min(100, int(round(cpu)))),
        'ram': max(0, min(100, int(round(load)))),
        'used': f'{used:.1f}',
        'total': f'{total:.0f}',
    }

def system_card():
    image=Image.new('RGB',SIZE,'#0c1421'); draw=ImageDraw.Draw(image)
    now=datetime.now()
    draw.text((8,5),now.strftime('%H:%M'),font=font(25,True),fill='white')
    draw.text((10,40),now.strftime('%d.%m.%Y'),font=font(11),fill='#9ab5d0')
    load,used,total=memory_info()
    draw.text((10,61),f'RAM {used:.1f}/{total:.0f} GB',font=font(11,True),fill='#68d9f0')
    draw.rounded_rectangle((10,83,149,87),radius=2,fill='#25354a')
    draw.rectangle((10,83,10+int(139*load/100),87),fill='#68d9f0')
    return image


def ensure_app_icon():
    """Generate kb884l_tray.ico next to the app if missing and return its Path."""
    ico_path = app_dir() / 'kb884l_tray.ico'
    if ico_path.is_file():
        return ico_path
    size = 64
    img = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((2, 2, size - 3, size - 3), radius=15, fill='#0c1424', outline='#5ce1e6', width=3)
    # Equalizer bars
    d.rounded_rectangle((14, 22, 22, 40), radius=3, fill='#5ce1e6')
    d.rounded_rectangle((28, 12, 36, 40), radius=3, fill='#7b61ff')
    d.rounded_rectangle((42, 18, 50, 40), radius=3, fill='#5ce1e6')
    # Bottom Now Bar capsule
    d.rounded_rectangle((12, 46, 52, 54), radius=4, fill='#5ce1e6')
    img.save(ico_path, format='ICO', sizes=[(16, 16), (32, 32), (48, 48), (64, 64)])
    return ico_path


class _GUID(ctypes.Structure):
    _fields_ = [
        ('Data1', wintypes.DWORD),
        ('Data2', wintypes.WORD),
        ('Data3', wintypes.WORD),
        ('Data4', ctypes.c_ubyte * 8),
    ]


class _NOTIFYICONDATAW(ctypes.Structure):
    _fields_ = [
        ('cbSize', wintypes.DWORD),
        ('hWnd', wintypes.HWND),
        ('uID', wintypes.UINT),
        ('uFlags', wintypes.UINT),
        ('uCallbackMessage', wintypes.UINT),
        ('hIcon', wintypes.HICON),
        ('szTip', wintypes.WCHAR * 128),
        ('dwState', wintypes.DWORD),
        ('dwStateMask', wintypes.DWORD),
        ('szInfo', wintypes.WCHAR * 256),
        ('uTimeoutOrVersion', wintypes.UINT),
        ('szInfoTitle', wintypes.WCHAR * 64),
        ('dwInfoFlags', wintypes.DWORD),
        ('guidItem', _GUID),
        ('hBalloonIcon', wintypes.HICON),
    ]


_LRESULT = ctypes.c_ssize_t
_WNDPROC = ctypes.WINFUNCTYPE(_LRESULT, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)


class _WNDCLASSW(ctypes.Structure):
    _fields_ = [
        ('style', wintypes.UINT),
        ('lpfnWndProc', _WNDPROC),
        ('cbClsExtra', ctypes.c_int),
        ('cbWndExtra', ctypes.c_int),
        ('hInstance', wintypes.HINSTANCE),
        ('hIcon', wintypes.HICON),
        ('hCursor', wintypes.HANDLE),
        ('hbrBackground', wintypes.HBRUSH),
        ('lpszMenuName', wintypes.LPCWSTR),
        ('lpszClassName', wintypes.LPCWSTR),
    ]


class SystemTrayIcon:
    """Native Win32 System Tray notification icon with left-click restore and context menu."""

    def __init__(self, icon_path, tooltip='KB884L Now Bar Studio', on_open=None, on_sync=None, on_exit=None):
        self.icon_path = Path(icon_path)
        self.tooltip = str(tooltip)[:127]
        self.on_open = on_open
        self.on_sync = on_sync
        self.on_exit = on_exit
        self.hwnd = None
        self.hicon = None
        self.ready = False
        self._ready_event = threading.Event()
        self._stop_requested = False
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        self._ready_event.wait(timeout=2.0)

    def _run(self):
        user32 = ctypes.windll.user32
        shell32 = ctypes.windll.shell32
        kernel32 = ctypes.windll.kernel32

        kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
        kernel32.GetModuleHandleW.restype = wintypes.HINSTANCE

        user32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
        user32.DefWindowProcW.restype = _LRESULT
        user32.RegisterClassW.argtypes = [ctypes.POINTER(_WNDCLASSW)]
        user32.RegisterClassW.restype = wintypes.ATOM
        user32.CreateWindowExW.argtypes = [
            wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
            ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
            wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID,
        ]
        user32.CreateWindowExW.restype = wintypes.HWND
        user32.LoadImageW.argtypes = [
            wintypes.HINSTANCE, wintypes.LPCWSTR, wintypes.UINT,
            ctypes.c_int, ctypes.c_int, wintypes.UINT,
        ]
        user32.LoadImageW.restype = wintypes.HICON
        user32.CreatePopupMenu.argtypes = []
        user32.CreatePopupMenu.restype = wintypes.HMENU
        user32.AppendMenuW.argtypes = [wintypes.HMENU, wintypes.UINT, wintypes.WPARAM, wintypes.LPCWSTR]
        user32.AppendMenuW.restype = wintypes.BOOL
        user32.DestroyMenu.argtypes = [wintypes.HMENU]
        user32.DestroyMenu.restype = wintypes.BOOL
        user32.GetCursorPos.argtypes = [ctypes.POINTER(wintypes.POINT)]
        user32.GetCursorPos.restype = wintypes.BOOL
        user32.SetForegroundWindow.argtypes = [wintypes.HWND]
        user32.SetForegroundWindow.restype = wintypes.BOOL
        user32.TrackPopupMenu.argtypes = [
            wintypes.HMENU, wintypes.UINT, ctypes.c_int, ctypes.c_int,
            ctypes.c_int, wintypes.HWND, wintypes.LPVOID,
        ]
        user32.TrackPopupMenu.restype = wintypes.UINT
        user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
        user32.PostMessageW.restype = wintypes.BOOL
        user32.DestroyWindow.argtypes = [wintypes.HWND]
        user32.DestroyWindow.restype = wintypes.BOOL
        user32.DestroyIcon.argtypes = [wintypes.HICON]
        user32.DestroyIcon.restype = wintypes.BOOL
        user32.RegisterWindowMessageW.argtypes = [wintypes.LPCWSTR]
        user32.RegisterWindowMessageW.restype = wintypes.UINT
        user32.SetTimer.argtypes = [wintypes.HWND, wintypes.WPARAM, wintypes.UINT, wintypes.LPVOID]
        user32.SetTimer.restype = wintypes.WPARAM
        user32.KillTimer.argtypes = [wintypes.HWND, wintypes.WPARAM]
        user32.KillTimer.restype = wintypes.BOOL
        shell32.Shell_NotifyIconW.argtypes = [wintypes.DWORD, ctypes.POINTER(_NOTIFYICONDATAW)]
        shell32.Shell_NotifyIconW.restype = wintypes.BOOL

        WM_DESTROY = 0x0002
        WM_TIMER = 0x0113
        WM_USER = 0x0400
        WM_TRAYICON = WM_USER + 20
        WM_LBUTTONUP = 0x0202
        WM_LBUTTONDBLCLK = 0x0203
        WM_RBUTTONUP = 0x0205
        WM_CONTEXTMENU = 0x007B
        NIM_ADD = 0x00000000
        NIM_DELETE = 0x00000002
        NIF_MESSAGE = 0x00000001
        NIF_ICON = 0x00000002
        NIF_TIP = 0x00000004
        IMAGE_ICON = 1
        LR_LOADFROMFILE = 0x00000010
        LR_DEFAULTSIZE = 0x00000040
        MF_STRING = 0x00000000
        MF_SEPARATOR = 0x00000800
        TPM_LEFTALIGN = 0x0000
        TPM_BOTTOMALIGN = 0x0020
        TPM_RIGHTBUTTON = 0x0002
        TPM_NONOTIFY = 0x0080
        TPM_RETURNCMD = 0x0100

        taskbar_created = user32.RegisterWindowMessageW('TaskbarCreated')
        hinst = kernel32.GetModuleHandleW(None)
        class_name = f'KB884LTrayWnd_{os.getpid()}'

        def _make_nid():
            nid = _NOTIFYICONDATAW()
            nid.cbSize = ctypes.sizeof(_NOTIFYICONDATAW)
            nid.hWnd = self.hwnd
            nid.uID = 1
            nid.uFlags = NIF_MESSAGE | NIF_ICON | NIF_TIP
            nid.uCallbackMessage = WM_TRAYICON
            nid.hIcon = self.hicon
            nid.szTip = self.tooltip
            return nid

        def _show_menu():
            menu = user32.CreatePopupMenu()
            if not menu:
                return
            try:
                user32.AppendMenuW(menu, MF_STRING, 1, t("KB884L Studio'yu Aç"))
                user32.AppendMenuW(menu, MF_STRING, 2, t('Şimdi Klavyeye Gönder (USB)'))
                user32.AppendMenuW(menu, MF_SEPARATOR, 0, None)
                user32.AppendMenuW(menu, MF_STRING, 3, t('Tamamen Çıkış'))
                pt = wintypes.POINT()
                user32.GetCursorPos(ctypes.byref(pt))
                user32.SetForegroundWindow(self.hwnd)
                cmd = user32.TrackPopupMenu(
                    menu,
                    TPM_LEFTALIGN | TPM_BOTTOMALIGN | TPM_RIGHTBUTTON | TPM_NONOTIFY | TPM_RETURNCMD,
                    pt.x, pt.y, 0, self.hwnd, None,
                )
                user32.PostMessageW(self.hwnd, 0, 0, 0)
            finally:
                user32.DestroyMenu(menu)
            if cmd == 1 and self.on_open:
                self.on_open()
            elif cmd == 2 and self.on_sync:
                self.on_sync()
            elif cmd == 3 and self.on_exit:
                self.on_exit()

        def _wnd_proc(hwnd, msg, wparam, lparam):
            if msg == WM_TRAYICON:
                ev = lparam & 0xFFFF
                if ev in (WM_LBUTTONUP, WM_LBUTTONDBLCLK):
                    if self.on_open:
                        self.on_open()
                elif ev in (WM_RBUTTONUP, WM_CONTEXTMENU):
                    _show_menu()
                return 0
            if msg == WM_TIMER:
                if not self.ready and self.hwnd and self.hicon:
                    self.ready = bool(shell32.Shell_NotifyIconW(NIM_ADD, ctypes.byref(_make_nid())))
                if self.ready:
                    user32.KillTimer(hwnd, 1)
                return 0
            if taskbar_created and msg == taskbar_created:
                self.ready = bool(shell32.Shell_NotifyIconW(NIM_ADD, ctypes.byref(_make_nid())))
                if self.ready:
                    user32.KillTimer(hwnd, 1)
                return 0
            if msg == WM_DESTROY:
                user32.PostQuitMessage(0)
                return 0
            return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

        self._proc_ref = _WNDPROC(_wnd_proc)
        wc = _WNDCLASSW()
        wc.lpfnWndProc = self._proc_ref
        wc.hInstance = hinst
        wc.lpszClassName = class_name
        user32.RegisterClassW(ctypes.byref(wc))

        self.hwnd = user32.CreateWindowExW(0, class_name, class_name, 0, 0, 0, 0, 0, None, None, hinst, None)
        self.hicon = user32.LoadImageW(None, str(self.icon_path), IMAGE_ICON, 0, 0, LR_LOADFROMFILE | LR_DEFAULTSIZE)
        if not self.hicon:
            # Fallback to default Win32 application icon (IDI_APPLICATION = 32512)
            self.hicon = user32.LoadIconW(None, ctypes.cast(32512, wintypes.LPCWSTR))

        if self.hwnd and self.hicon:
            self.ready = bool(shell32.Shell_NotifyIconW(NIM_ADD, ctypes.byref(_make_nid())))
            if not self.ready:
                user32.SetTimer(self.hwnd, 1, 2000, None)
        self._ready_event.set()

        msg = wintypes.MSG()
        while not self._stop_requested and user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))

        if self.hwnd:
            user32.KillTimer(self.hwnd, 1)
            nid = _NOTIFYICONDATAW()
            nid.cbSize = ctypes.sizeof(_NOTIFYICONDATAW)
            nid.hWnd = self.hwnd
            nid.uID = 1
            shell32.Shell_NotifyIconW(NIM_DELETE, ctypes.byref(nid))
            user32.DestroyWindow(self.hwnd)
            self.hwnd = None
        if self.hicon:
            user32.DestroyIcon(self.hicon)
            self.hicon = None
        self.ready = False

    def stop(self):
        self._stop_requested = True
        if self.hwnd:
            try:
                ctypes.windll.user32.PostMessageW(self.hwnd, 0x0012, 0, 0)  # WM_QUIT
            except Exception:
                pass
