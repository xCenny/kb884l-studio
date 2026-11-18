"""KB884L Now Bar Studio — 160x96 TFT Now Bar designer, GIF tool, and direct USB uploader."""
from __future__ import annotations
import asyncio
import concurrent.futures
from datetime import datetime
import json
import os
from pathlib import Path
import queue
import socket
import sys
import threading
import time
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from PIL import Image, ImageTk

from i18n import LANGUAGES, get_language, set_language, t
from keyboard_usb import Keyboard, KeyboardError, check_connection
from screen_ui import LAYOUTS, THEMES, render_nowbar, render_nowbar_frames
from studio_core import (
    SystemTrayIcon,
    add_to_driver,
    ensure_app_icon,
    load_bg_image,
    load_settings,
    media_info,
    prepare_gif,
    register_cover_image,
    save_gif,
    save_settings,
    set_windows_startup,
    system_stats,
)

IPC_HOST = '127.0.0.1'
IPC_PORT = 48884

BACKGROUND = '#0c1018'
PANEL = '#151d2a'
INPUT_BG = '#0f1622'
TEXT = '#ecf1fa'
MUTED = '#99abc2'
ACCENT = '#67d9ef'
SUCCESS = '#3be287'
WARN = '#ffbd77'


class Studio(tk.Tk):
    def __init__(self, ipc_sock=None, start_hidden=False, demo=False, language=None, file_paths=None):
        super().__init__()
        self._demo = bool(demo)
        saved = {} if self._demo else load_settings()
        set_language(language or saved.get('language', 'en'))
        self._initializing = True
        self.ipc_sock = ipc_sock
        self.title('KB884L Now Bar Studio')
        self.geometry('1080x780')
        self.minsize(960, 720)
        self.configure(bg=BACKGROUND)
        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)

        self.media_executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
        self.upload_executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
        self.gif_executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)

        self.media_future = None
        self.upload_future = None
        self.info = {'available': False, 'playing': False, 'title': t('Medya bekleniyor'),
                     'artist': t('Spotify veya tarayıcıda oynat'), 'position': 0.0, 'duration': 0.0,
                     'source': '', 'has_cover': False, 'cover_hash': ''}
        self.stats = ({'cpu': 23, 'ram': 46, 'used': '7.4', 'total': '16'}
                      if self._demo else system_stats())
        self.last_error = ''
        self.tab = 'nowbar'
        self.media = None
        self.original_path = None
        self.current_frame = None
        self.frame_index = 0
        self.gif_busy = False
        self.uploading = False
        self._closing = False
        self._quit_after_upload = False
        self._retry_failures = 0
        self._next_retry_at = 0.0
        self.usb_connected = False
        self.usb_message = t('USB kontrol ediliyor…')
        self.last_sync_signature = None
        self.last_sync_time = 0.0
        self.last_sync_clock = ''
        self.last_sync_stats = (0, 0)
        self.preview_anim_step = 0
        self.cached_nowbar_frames = None
        self.cached_nowbar_durations = None
        self.cached_nowbar_key = None
        self._preview_delay = 120

        if getattr(self, '_demo', False):
            saved = {'layout': 'nowbar_artwork', 'mode': 'fast_anim', 'smart_switch': False}
            cover = Image.new('RGB', (64, 64))
            for y in range(64):
                for x in range(64):
                    cover.putpixel((x, y), (35 + x * 3, 30 + y * 2, max(40, 220 - x - y)))
            self.info = {'available': True, 'playing': True, 'title': 'Midnight Drive',
                         'artist': 'Studio Sessions', 'position': 95.0, 'duration': 218.0,
                         'source': 'Demo', 'has_cover': True,
                         'cover_hash': register_cover_image(cover)}
        self.layout_names = {t(v): k for k, v in LAYOUTS.items()}
        self.theme_names = {t(v['name']): k for k, v in THEMES.items()}
        self.sync_interval_map = {
            t('Sadece Şarkı/Durum Değişiminde'): 'event',
            t('Her 1 Dakikada Bir (Saat + Şarkı Değişimi)'): '1m',
            t('Her 30 Saniyede Bir'): '30s',
        }
        sync_reverse = {v: k for k, v in self.sync_interval_map.items()}

        init_layout = saved.get('layout') if saved.get('layout') in LAYOUTS else 'nowbar_dual'
        init_theme = saved.get('theme') if saved.get('theme') in THEMES else 'cover'
        init_mode = saved.get('mode') if saved.get('mode') in ('static', 'fast_anim', 'animated', 'device_loop') else 'static'
        init_sync_label = sync_reverse.get(
            saved.get('sync_interval'),
            t('Sadece Şarkı/Durum Değişiminde'),
        )
        raw_bg = str(saved.get('bg_image_path', '') or '')
        self.bg_image_path = raw_bg if (raw_bg and Path(raw_bg).is_file()) else ''

        # Tk variables (loaded persistently)
        self.layout_var = tk.StringVar(value=init_layout)
        self.layout_label_var = tk.StringVar(value=t(LAYOUTS[init_layout]))
        self.theme_label_var = tk.StringVar(value=t(THEMES[init_theme]['name']))
        self.label_var = tk.StringVar(value=str(saved.get('label', 'STUDIO'))[:12])
        self.note_var = tk.StringVar(value=str(saved.get('note', t('Hazır · Now Bar')))[:64])
        self.mode_var = tk.StringVar(value=init_mode)
        self.sync_interval_var = tk.StringVar(value=init_sync_label)
        self.auto_sync_var = tk.BooleanVar(value=bool(saved.get('auto_sync', False)))
        self.smart_switch_var = tk.BooleanVar(value=bool(saved.get('smart_switch', True)))
        self.idle_clock_sync_var = tk.BooleanVar(value=bool(saved.get('idle_clock_sync', True)))
        self.startup_var = tk.BooleanVar(value=bool(saved.get('run_on_startup', False)))
        self.bg_close_var = tk.BooleanVar(value=bool(saved.get('close_to_background', True)))
        self.bg_name_var = tk.StringVar(
            value=Path(self.bg_image_path).name if self.bg_image_path else t('Varsayılan Gradyan')
        )
        self.fit_var = tk.StringVar(value='contain')
        self.language_var = tk.StringVar(value=LANGUAGES[get_language()])
        self.progress_var = tk.DoubleVar(value=0.0)
        self.status_var = tk.StringVar(value=t('Now Bar arayüzünü özelleştir ve tek tıkla USB’den klavyeye gönder.'))

        if not self._demo and self.startup_var.get():
            set_windows_startup(True)

        icon_path = Path(__file__).with_name('kb884l_tray.ico') if self._demo else ensure_app_icon()
        try:
            self.iconbitmap(default=str(icon_path))
        except Exception:
            pass
        self.tray = None if self._demo else SystemTrayIcon(
            icon_path,
            'KB884L Now Bar Studio',
            on_open=lambda: self.after(0, self.restore_window),
            on_sync=lambda: self.after(0, self.upload_usb_clicked),
            on_exit=lambda: self.after(0, self.quit_completely),
        )

        self._setup_styles()
        self._build_ui()
        if getattr(self, '_demo', False):
            self.title('KB884L Studio — ' + t('Demo önizleme · cihaz erişimi yok'))
            self.usb_message = t('Demo önizleme · cihaz erişimi yok')
            self.usb_label.configure(text=self.usb_message, fg=ACCENT)
            self.status_var.set(t('Demo modu: USB, ağ, başlangıç ve ayar kaydı kapalı.'))
            self.upload_btn.configure(state='disabled')
            self.auto_sync_chk.configure(state='disabled')
        self._initializing = False
        self.persist_settings()

        if self.ipc_sock is not None:
            threading.Thread(target=self._listen_ipc, daemon=True).start()

        if start_hidden:
            self.withdraw()

        self.protocol('WM_DELETE_WINDOW', self.on_window_close)
        self.after(60, self.animate)
        self.after(200, self.refresh_telemetry)
        self.after(400, self.refresh_usb_status)

        file_args = file_paths or []
        if file_args:
            self.after(300, lambda: self.load_gif(Path(file_args[0])))

    def _setup_styles(self):
        style = ttk.Style(self)
        style.theme_use('clam')
        style.configure('TButton', font=('Segoe UI', 9), padding=(8, 6),
                        background='#25334a', foreground=TEXT, borderwidth=0)
        style.map('TButton', background=[('active', '#344965'), ('disabled', '#1a2333')],
                  foreground=[('disabled', '#64748b')])
        style.configure('Accent.TButton', background=ACCENT, foreground='#081822',
                        font=('Segoe UI Semibold', 10), padding=(10, 8))
        style.map('Accent.TButton', background=[('active', '#8de7f7'), ('disabled', '#284a54')])
        style.configure('TRadiobutton', background=PANEL, foreground=TEXT, font=('Segoe UI', 9))
        style.map('TRadiobutton', background=[('active', PANEL)])
        style.configure('TCheckbutton', background=BACKGROUND, foreground=TEXT, font=('Segoe UI Semibold', 9))
        style.map('TCheckbutton', background=[('active', BACKGROUND)])
        style.configure('Panel.TCheckbutton', background=PANEL, foreground=TEXT, font=('Segoe UI', 9))
        style.map('Panel.TCheckbutton', background=[('active', PANEL)])
        style.configure('TCombobox', fieldbackground=INPUT_BG, background='#25334a',
                        foreground=TEXT, arrowcolor=ACCENT, borderwidth=0, padding=4)
        style.map('TCombobox', fieldbackground=[('readonly', INPUT_BG), ('disabled', '#101724')],
                  selectbackground=[('readonly', INPUT_BG)], selectforeground=[('readonly', TEXT)],
                  foreground=[('disabled', '#5b6b82')])
        style.configure('Horizontal.TProgressbar', troughcolor='#1b2536', background=ACCENT, thickness=6)

    def _build_ui(self):
        top = tk.Frame(self, bg=BACKGROUND)
        top.grid(row=0, column=0, sticky='ew', padx=26, pady=(14, 8))

        top_left = tk.Frame(top, bg=BACKGROUND)
        top_left.pack(side='left', anchor='w')
        tk.Label(top_left, text='KB884L-TUR', font=('Segoe UI', 11, 'bold'), fg=ACCENT, bg=BACKGROUND).pack(anchor='w')
        tk.Label(top_left, text=t('Now Bar Ekran Studio'), font=('Segoe UI', 22, 'bold'), fg=TEXT, bg=BACKGROUND).pack(anchor='w')
        tk.Label(top_left, text=t('160 × 96 TFT-LCD  ·  Doğrudan USB HID ekran özelleştirme'),
                 font=('Segoe UI', 10), fg=MUTED, bg=BACKGROUND).pack(anchor='w', pady=(2, 0))

        top_right = tk.Frame(top, bg=PANEL, highlightthickness=1, highlightbackground='#263650')
        top_right.pack(side='right', anchor='ne')
        tk.Label(top_right, text=t('Başlangıç & Sistem Tepsisi'), font=('Segoe UI', 9, 'bold'), fg=ACCENT, bg=PANEL).pack(
            anchor='w', padx=12, pady=(6, 2))
        ttk.Checkbutton(
            top_right, text=t('Bilgisayar Açıldığında Otomatik Başlat'),
            style='Panel.TCheckbutton', variable=self.startup_var, command=self.on_startup_toggled,
        ).pack(anchor='w', padx=12, pady=1)
        ttk.Checkbutton(
            top_right, text=t('Kapatınca (X) Sistem Tepsisine Küçült'),
            style='Panel.TCheckbutton', variable=self.bg_close_var, command=self.persist_settings,
        ).pack(anchor='w', padx=12, pady=1)
        ttk.Button(top_right, text=t('Şimdi Tepsiye Gizle'), command=self.hide_to_tray).pack(
            fill='x', padx=12, pady=(4, 7))

        tabs = tk.Frame(self, bg=BACKGROUND)
        tabs.grid(row=1, column=0, sticky='ew', padx=26)
        self.tab_nowbar_btn = ttk.Button(tabs, text=t('Now Bar Tasarımcısı'), style='Accent.TButton',
                                         command=lambda: self.switch_tab('nowbar'))
        self.tab_nowbar_btn.pack(side='left', padx=(0, 8))
        self.tab_gif_btn = ttk.Button(tabs, text=t('Özel GIF Hazırlama'),
                                      command=lambda: self.switch_tab('gif'))
        self.tab_gif_btn.pack(side='left')
        self.language_combo = ttk.Combobox(tabs, textvariable=self.language_var,
                                           values=list(LANGUAGES.values()), state='readonly', width=10)
        self.language_combo.pack(side='right')
        self.language_combo.bind('<<ComboboxSelected>>', self.on_language_changed)
        tk.Label(tabs, text=t('Dil'), fg=MUTED, bg=BACKGROUND,
                 font=('Segoe UI', 9)).pack(side='right', padx=(8, 6))

        content = tk.Frame(self, bg=BACKGROUND)
        content.grid(row=2, column=0, sticky='nsew', padx=26, pady=12)

        # Left preview panel
        left = tk.Frame(content, bg=PANEL)
        left.pack(side='left', fill='both', expand=True, padx=(0, 18))
        left.columnconfigure(0, weight=1)
        left.rowconfigure(2, weight=1)

        self.heading = tk.Label(left, text=t('Now Bar Önizlemesi'), font=('Segoe UI', 15, 'bold'), fg=TEXT, bg=PANEL)
        self.heading.grid(row=0, column=0, sticky='w', padx=18, pady=(14, 4))
        self.description = tk.Label(
            left,
            text=t('Medya, saat, CPU ve RAM bilgilerini 160×96 tuvalde önizle. Klavye güncellemeleri görüntü yüklemesi gerektirir.'),
            font=('Segoe UI', 9), fg=MUTED, bg=PANEL, wraplength=540, justify='left',
        )
        self.description.grid(row=1, column=0, sticky='w', padx=18)

        self.canvas = tk.Canvas(left, width=480, height=288, bg='#05080f', highlightthickness=1, highlightbackground='#263650')
        self.canvas.grid(row=2, column=0, sticky='nsew', padx=18, pady=12)
        self.canvas.bind('<Configure>', self.resize_preview)

        info_bar = tk.Frame(left, bg=PANEL)
        info_bar.grid(row=3, column=0, sticky='ew', padx=18, pady=(0, 6))
        self.details = tk.Label(info_bar, text=t('Sistem ve medya okunuyor…'), font=('Segoe UI', 9), fg=MUTED, bg=PANEL, anchor='w')
        self.details.pack(fill='x')
        self.usb_label = tk.Label(info_bar, text=t('USB kontrol ediliyor…'), font=('Segoe UI', 9, 'bold'), fg=WARN, bg=PANEL, anchor='w')
        self.usb_label.pack(fill='x', pady=(2, 0))

        self.progress = ttk.Progressbar(left, variable=self.progress_var, mode='determinate', maximum=100)
        self.progress.grid(row=4, column=0, sticky='ew', padx=18, pady=(4, 14))

        # Right configuration & action panel
        right = tk.Frame(content, bg=BACKGROUND, width=340)
        right.pack(side='right', fill='y')
        right.pack_propagate(False)
        right.grid_propagate(False)
        right.rowconfigure(0, weight=1)
        right.columnconfigure(0, weight=1)

        self.config_canvas = tk.Canvas(right, bg=BACKGROUND, highlightthickness=0, width=320)
        self.config_canvas.grid(row=0, column=0, sticky='nsew')
        config_scrollbar = ttk.Scrollbar(right, orient='vertical', command=self.config_canvas.yview)
        config_scrollbar.grid(row=0, column=1, sticky='ns')
        self.config_canvas.configure(yscrollcommand=config_scrollbar.set)
        self.right_top = tk.Frame(self.config_canvas, bg=BACKGROUND)
        self._config_window = self.config_canvas.create_window((0, 0), window=self.right_top, anchor='nw')
        self.right_top.bind(
            '<Configure>', lambda _event: self.config_canvas.configure(scrollregion=self.config_canvas.bbox('all'))
        )
        self.config_canvas.bind(
            '<Configure>', lambda event: self.config_canvas.itemconfigure(self._config_window, width=event.width)
        )
        if not getattr(self, '_wheel_bound', False):
            self.bind_all('<MouseWheel>', self._scroll_configuration, add='+')
            self._wheel_bound = True

        # Now Bar controls frame
        self.nowbar_panel = tk.Frame(self.right_top, bg=BACKGROUND)
        self._build_nowbar_controls(self.nowbar_panel)
        self.nowbar_panel.pack(fill='x')

        # GIF controls frame (hidden initially)
        self.gif_panel = tk.Frame(self.right_top, bg=BACKGROUND)
        self._build_gif_controls(self.gif_panel)

        # Shared action buttons at bottom of right panel
        actions = tk.Frame(right, bg=BACKGROUND)
        actions.grid(row=1, column=0, columnspan=2, sticky='ew', pady=(8, 0))

        self.upload_btn = ttk.Button(actions, text=t('Doğrudan Klavyeye Yükle (USB)'), style='Accent.TButton',
                                     command=self.upload_usb_clicked)
        self.upload_btn.pack(fill='x', pady=(0, 6))

        self.auto_sync_chk = ttk.Checkbutton(
            actions, text=t('Otomatik Görüntü Aktarımı (Auto-Sync)'),
            variable=self.auto_sync_var, command=self.on_auto_sync_toggled,
        )
        self.auto_sync_chk.pack(anchor='w', pady=(0, 8))

        secondary_row = tk.Frame(actions, bg=BACKGROUND)
        secondary_row.pack(fill='x')
        secondary_row.columnconfigure(0, weight=1)
        secondary_row.columnconfigure(1, weight=1)
        secondary_row.columnconfigure(2, weight=1)
        ttk.Button(secondary_row, text=t('HAVIT’e Ekle'), command=self.register).grid(
            row=0, column=0, sticky='ew', padx=(0, 3))
        ttk.Button(secondary_row, text=t('GIF Kaydet'), command=self.export).grid(
            row=0, column=1, sticky='ew', padx=3)
        ttk.Button(secondary_row, text=t('Tamamen Çıkış'), command=self.quit_completely).grid(
            row=0, column=2, sticky='ew', padx=(3, 0))

        footer = tk.Label(self, textvariable=self.status_var, font=('Segoe UI', 9), fg=ACCENT,
                          bg=BACKGROUND, wraplength=1000, anchor='w', justify='left')
        footer.grid(row=3, column=0, sticky='ew', padx=26, pady=(0, 10))

    def _scroll_configuration(self, event):
        """Scroll only while the pointer is over the configuration controls."""
        widget = self.winfo_containing(event.x_root, event.y_root)
        while widget is not None:
            if widget is self.right_top or widget is self.config_canvas:
                self.config_canvas.yview_scroll(-int(event.delta / 120), 'units')
                return 'break'
            widget = getattr(widget, 'master', None)

    def _build_nowbar_controls(self, parent):
        layout_box = tk.Frame(parent, bg=PANEL)
        layout_box.pack(fill='x', pady=(0, 6))
        tk.Label(layout_box, text=t('Now Bar Düzeni'), font=('Segoe UI', 10, 'bold'), fg=TEXT, bg=PANEL).pack(
            anchor='w', padx=12, pady=(6, 3))
        self.layout_cb = ttk.Combobox(
            layout_box,
            textvariable=self.layout_label_var,
            state='disabled' if self.smart_switch_var.get() else 'readonly',
            values=[t(value) for value in LAYOUTS.values()],
        )
        self.layout_cb.pack(fill='x', padx=12, pady=(0, 4))
        self.layout_cb.bind('<<ComboboxSelected>>', self.on_layout_combo_changed)
        ttk.Checkbutton(
            layout_box,
            text=t('Oynatma Başlayınca Otomatik Vitrin Now Bar’a Geç'),
            style='Panel.TCheckbutton',
            variable=self.smart_switch_var,
            command=self.on_smart_switch_toggled,
        ).pack(anchor='w', padx=12, pady=(2, 7))

        style_box = tk.Frame(parent, bg=PANEL)
        style_box.pack(fill='x', pady=(0, 6))
        tk.Label(style_box, text=t('Görünüm & Arka Plan'), font=('Segoe UI', 10, 'bold'), fg=TEXT, bg=PANEL).pack(
            anchor='w', padx=12, pady=(6, 3))

        tk.Label(style_box, text=t('Renk Teması'), font=('Segoe UI', 8), fg=MUTED, bg=PANEL).pack(anchor='w', padx=12)
        theme_cb = ttk.Combobox(style_box, textvariable=self.theme_label_var, state='readonly',
                                values=[t(v['name']) for v in THEMES.values()])
        theme_cb.pack(fill='x', padx=12, pady=(2, 5))
        theme_cb.bind('<<ComboboxSelected>>', lambda _e: self.on_nowbar_setting_changed())

        bg_row = tk.Frame(style_box, bg=PANEL)
        bg_row.pack(fill='x', padx=12, pady=(2, 5))
        ttk.Button(bg_row, text=t('Arka Plan Görseli Seç…'), command=self.pick_bg_image).pack(side='left')
        ttk.Button(bg_row, text=t('Kaldır'), command=self.clear_bg_image).pack(side='left', padx=(6, 6))
        tk.Label(bg_row, textvariable=self.bg_name_var, font=('Segoe UI', 8), fg=MUTED, bg=PANEL, anchor='w').pack(
            side='left', fill='x', expand=True
        )

        row_inputs = tk.Frame(style_box, bg=PANEL)
        row_inputs.pack(fill='x', padx=12, pady=(0, 8))
        row_inputs.columnconfigure(0, weight=1)
        row_inputs.columnconfigure(1, weight=2)
        tk.Label(row_inputs, text=t('Üst Etiket'), font=('Segoe UI', 8), fg=MUTED, bg=PANEL).grid(row=0, column=0, sticky='w')
        tk.Label(row_inputs, text=t('Boşta Durum Yazısı'), font=('Segoe UI', 8), fg=MUTED, bg=PANEL).grid(
            row=0, column=1, sticky='w', padx=(8, 0))
        label_entry = tk.Entry(row_inputs, textvariable=self.label_var, bg=INPUT_BG, fg=TEXT,
                               insertbackground=ACCENT, relief='flat', font=('Segoe UI', 9))
        label_entry.grid(row=1, column=0, sticky='ew', ipady=3)
        note_entry = tk.Entry(row_inputs, textvariable=self.note_var, bg=INPUT_BG, fg=TEXT,
                              insertbackground=ACCENT, relief='flat', font=('Segoe UI', 9))
        note_entry.grid(row=1, column=1, sticky='ew', padx=(8, 0), ipady=3)
        if not getattr(self, '_entry_traces_initialized', False):
            self.label_var.trace_add('write', lambda *_: self.on_nowbar_setting_changed())
            self.note_var.trace_add('write', lambda *_: self.on_nowbar_setting_changed())
            self._entry_traces_initialized = True

        mode_box = tk.Frame(parent, bg=PANEL)
        mode_box.pack(fill='x', pady=(0, 6))
        tk.Label(mode_box, text=t('Çalışma Modu & Yenileme'), font=('Segoe UI', 10, 'bold'), fg=TEXT, bg=PANEL).pack(
            anchor='w', padx=12, pady=(6, 2))
        ttk.Radiobutton(mode_box, text=t('Anlık Kart (1 Kare - ~1 sn En Hızlı Geçiş)'),
                        variable=self.mode_var, value='static', command=self.on_nowbar_setting_changed).pack(
            anchor='w', padx=12, pady=1)
        ttk.Radiobutton(mode_box, text=t('Hızlı Animasyon (8 Kare - Ekolayzır & Kayan Yazı)'),
                        variable=self.mode_var, value='fast_anim', command=self.on_nowbar_setting_changed).pack(
            anchor='w', padx=12, pady=1)
        ttk.Radiobutton(mode_box, text=t('Tam Animasyon (16 Kare - Dönüşümlü & Uzun Akış)'),
                        variable=self.mode_var, value='animated', command=self.on_nowbar_setting_changed).pack(
            anchor='w', padx=12, pady=1)
        ttk.Radiobutton(mode_box, text=t('Akıcı cihaz döngüsü (96 kareye kadar · Tek yükleme)'),
                        variable=self.mode_var, value='device_loop', command=self.on_nowbar_setting_changed).pack(
            anchor='w', padx=12, pady=1)
        tk.Label(
            mode_box, text=t('Klavye döngüyü kendi oynatır; şarkı veya tasarım değişince yeniden aktarılır.\n'
                           'Bu modda saat ve sistem değerleri aktarım anını gösterir.'),
            font=('Segoe UI', 8), fg=MUTED, bg=PANEL, wraplength=270, justify='left',
        ).pack(anchor='w', padx=12, pady=(2, 4))

        tk.Label(mode_box, text=t('Otomatik Yenileme Sıklığı'), font=('Segoe UI', 8), fg=MUTED, bg=PANEL).pack(
            anchor='w', padx=12, pady=(4, 0))
        sync_cb = ttk.Combobox(mode_box, textvariable=self.sync_interval_var, state='readonly',
                               values=list(self.sync_interval_map.keys()))
        sync_cb.pack(fill='x', padx=12, pady=(2, 4))
        sync_cb.bind('<<ComboboxSelected>>', lambda _e: self.on_nowbar_setting_changed())
        ttk.Checkbutton(
            mode_box, text=t('Şarkı Çalmıyorken Saat Değişiminde Yenile'),
            style='Panel.TCheckbutton', variable=self.idle_clock_sync_var,
            command=self.on_nowbar_setting_changed,
        ).pack(anchor='w', padx=12, pady=(2, 7))

    def _build_gif_controls(self, parent):
        ttk.Button(parent, text=t('GIF Seç (.gif)'), style='Accent.TButton', command=self.pick_gif).pack(fill='x')
        opts = tk.Frame(parent, bg=PANEL)
        opts.pack(fill='x', pady=12)
        tk.Label(opts, text=t('Ekrana Yerleştirme'), font=('Segoe UI', 10, 'bold'), fg=TEXT, bg=PANEL).pack(
            anchor='w', padx=12, pady=(10, 6))
        ttk.Radiobutton(opts, text=t('Tamamı görünsün'), variable=self.fit_var, value='contain',
                        command=self.refit_gif).pack(anchor='w', padx=12, pady=3)
        ttk.Radiobutton(opts, text=t('Ekranı doldur / kenarları kırp'), variable=self.fit_var, value='cover',
                        command=self.refit_gif).pack(anchor='w', padx=12, pady=(3, 10))

        tip_box = tk.Frame(parent, bg=PANEL)
        tip_box.pack(fill='x', pady=(4, 0))
        tk.Label(tip_box, text=t('Doğrudan USB Aktarımı'), font=('Segoe UI', 10, 'bold'), fg=TEXT, bg=PANEL).pack(
            anchor='w', padx=12, pady=(10, 4))
        tk.Label(
            tip_box,
            text=t('Hazırlanan GIF kareleri doğrudan USB üzerinden klavyeye yüklenebilir veya HAVIT veritabanına eklenebilir. '
                 'Doğrudan USB aktarımı sırasında HAVIT yazılımının kapalı olması gerekir.'),
            font=('Segoe UI', 9), fg=MUTED, bg=PANEL, wraplength=270, justify='left',
        ).pack(anchor='w', padx=12, pady=(0, 10))

    def current_theme_key(self):
        return self.theme_names.get(self.theme_label_var.get(), 'cover')

    def on_language_changed(self, _event=None):
        """Rebuild labels without replacing workers, tray or USB transactions."""
        selected = next((key for key, name in LANGUAGES.items()
                         if name == self.language_var.get()), get_language())
        if selected == get_language():
            return
        if self.uploading or self.gif_busy:
            self.language_var.set(LANGUAGES[get_language()])
            self.status_var.set(t('Dili değiştirmeden önce aktarımın bitmesini bekle.'))
            return
        theme = self.current_theme_key()
        interval = self.current_sync_interval_key()
        set_language(selected)
        self.layout_names = {t(value): key for key, value in LAYOUTS.items()}
        self.theme_names = {t(value['name']): key for key, value in THEMES.items()}
        self.sync_interval_map = {
            t('Sadece Şarkı/Durum Değişiminde'): 'event',
            t('Her 1 Dakikada Bir (Saat + Şarkı Değişimi)'): '1m',
            t('Her 30 Saniyede Bir'): '30s',
        }
        self.layout_label_var.set(t(LAYOUTS[self.layout_var.get()]))
        self.theme_label_var.set(t(THEMES[theme]['name']))
        self.sync_interval_var.set(next(label for label, key in self.sync_interval_map.items()
                                        if key == interval))
        if not self.bg_image_path:
            self.bg_name_var.set(t('Varsayılan Gradyan'))
        self.language_var.set(LANGUAGES[selected])
        self.cached_nowbar_frames = None
        self.cached_nowbar_durations = None
        self.cached_nowbar_key = None
        self._initializing = True
        for child in self.winfo_children():
            child.destroy()
        self._build_ui()
        self.switch_tab(self.tab)
        self._initializing = False
        self.persist_settings()
        self.usb_label.configure(text=t(self.usb_message), fg=SUCCESS if self.usb_connected else WARN)
        self.status_var.set(t('Dil değiştirildi.'))
        if getattr(self, '_demo', False):
            self.title('KB884L Studio — ' + t('Demo önizleme · cihaz erişimi yok'))
            self.status_var.set(t('Demo modu: USB, ağ, başlangıç ve ayar kaydı kapalı.'))
            self.upload_btn.configure(state='disabled')
            self.auto_sync_chk.configure(state='disabled')

    def current_sync_interval_key(self):
        return self.sync_interval_map.get(self.sync_interval_var.get(), 'event')

    def is_media_playing(self):
        return bool(self.info.get('available') and self.info.get('playing'))

    def effective_layout(self):
        if self.smart_switch_var.get():
            return 'nowbar_artwork' if self.is_media_playing() else 'nowbar_dual'
        return self.layout_var.get()

    def effective_mode(self, mode_override=None):
        return self.mode_var.get() if mode_override is None else mode_override

    def persist_settings(self):
        if getattr(self, '_initializing', False) or getattr(self, '_demo', False):
            return
        save_settings({
            'language': get_language(),
            'layout': self.layout_var.get(),
            'theme': self.current_theme_key(),
            'label': self.label_var.get(),
            'note': self.note_var.get(),
            'mode': self.mode_var.get(),
            'sync_interval': self.current_sync_interval_key(),
            'auto_sync': bool(self.auto_sync_var.get()),
            'smart_switch': bool(self.smart_switch_var.get()),
            'idle_clock_sync': bool(self.idle_clock_sync_var.get()),
            'bg_image_path': self.bg_image_path,
            'run_on_startup': bool(self.startup_var.get()),
            'close_to_background': bool(self.bg_close_var.get()),
        })

    def on_layout_combo_changed(self, _e=None):
        key = self.layout_names.get(self.layout_label_var.get(), 'nowbar_dual')
        self.layout_var.set(key)
        self.on_nowbar_setting_changed()

    def on_smart_switch_toggled(self):
        self.layout_cb.configure(state='disabled' if self.smart_switch_var.get() else 'readonly')
        self.on_nowbar_setting_changed()

    def on_startup_toggled(self):
        if getattr(self, '_demo', False):
            self.startup_var.set(False)
            self.status_var.set(t('Demo modu: USB, ağ, başlangıç ve ayar kaydı kapalı.'))
            return
        enabled = bool(self.startup_var.get())
        ok = set_windows_startup(enabled)
        self.persist_settings()
        if ok:
            self.status_var.set(
                t('Windows başlangıcında arka planda çalışacak.') if enabled
                else t('Windows otomatik başlatma kaldırıldı.')
            )

    def pick_bg_image(self):
        path = filedialog.askopenfilename(
            title=t('İkili Now Bar Arka Plan Görseli Seç'),
            filetypes=[(t('Görsel Dosyaları'), '*.png;*.jpg;*.jpeg;*.webp;*.bmp;*.gif')],
        )
        if path and load_bg_image(path) is not None:
            self.bg_image_path = str(path)
            self.bg_name_var.set(Path(path).name)
            self.on_nowbar_setting_changed()
            self.status_var.set(t('Arka plan görseli seçildi: {name}', name=Path(path).name))
        elif path:
            messagebox.showerror(t('Görsel Yüklenemedi'), t('Seçilen görsel dosyası açılamadı.'))

    def clear_bg_image(self):
        self.bg_image_path = ''
        self.bg_name_var.set(t('Varsayılan Gradyan'))
        self.on_nowbar_setting_changed()
        self.status_var.set(t('Arka plan görseli temizlendi.'))

    def on_nowbar_setting_changed(self):
        self.cached_nowbar_frames = None
        self.cached_nowbar_durations = None
        self.cached_nowbar_key = None
        self.preview_anim_step = 0
        self.persist_settings()
        if self.tab == 'nowbar':
            if self.state() != 'withdrawn':
                self.render_nowbar_preview_now()
            self.maybe_auto_sync()

    def on_auto_sync_toggled(self):
        if getattr(self, '_demo', False):
            self.auto_sync_var.set(False)
            self.status_var.set(t('Demo modunda klavyeye veri gönderilmez.'))
            return
        self.persist_settings()
        if self.auto_sync_var.get():
            self.last_sync_signature = None
            self.last_sync_clock = ''
            self.last_sync_time = 0.0
            self._retry_failures = 0
            self._next_retry_at = 0.0
            self.status_var.set(t('Otomatik görüntü aktarımı açıldı. Yenilemeler klavyenin yükleme ekranını gösterebilir.'))
            self.maybe_auto_sync(force=True)
        else:
            self.status_var.set(t('Otomatik görüntü aktarımı kapatıldı.'))

    def switch_tab(self, key):
        self.tab = key
        if key == 'nowbar':
            self.tab_nowbar_btn.configure(style='Accent.TButton')
            self.tab_gif_btn.configure(style='TButton')
            self.gif_panel.pack_forget()
            self.nowbar_panel.pack(fill='x')
            self.auto_sync_chk.configure(state='disabled' if self._demo else 'normal')
            self.heading.configure(text=t('Now Bar Önizlemesi'))
            self.description.configure(
                text=t('Medya, saat, CPU ve RAM bilgilerini 160×96 tuvalde önizle. Klavye güncellemeleri görüntü yüklemesi gerektirir.')
            )
            self.render_nowbar_preview_now()
        else:
            self.tab_gif_btn.configure(style='Accent.TButton')
            self.tab_nowbar_btn.configure(style='TButton')
            self.nowbar_panel.pack_forget()
            self.gif_panel.pack(fill='x')
            self.auto_sync_chk.configure(state='disabled')
            self.heading.configure(text=t('GIF’i Bir Kez Seç'))
            self.description.configure(
                text=t('Kareler, 160×96 boyut ve saydamlık otomatik düzenlenir; 255 kareye kadar desteklenir.')
            )
            self.canvas.delete('all')
            self.current_frame = None
            self.frame_index = 0
            if not self.media:
                self.details.configure(text=t('Henüz GIF seçilmedi'))
                self._draw_canvas_placeholder(t('GIF önizlemesi'))
            else:
                m = self.media
                self.details.configure(
                    text=t('{name}  ·  {source} → {count} kare  ·  {seconds:.1f} sn',
                           name=m['name'], source=m['source_frames'], count=len(m['frames']), seconds=m['duration']/1000)
                )

    def _draw_canvas_placeholder(self, text):
        w = max(1, self.canvas.winfo_width())
        h = max(1, self.canvas.winfo_height())
        self.canvas.delete('all')
        self.canvas.create_text(w // 2, h // 2, text=text, fill='#526278', font=('Segoe UI', 16))

    def show_image(self, image):
        self.current_frame = image
        width = max(1, self.canvas.winfo_width())
        height = max(1, self.canvas.winfo_height())
        scale = min((width - 16) / 160, (height - 16) / 96)
        scale = max(1.0, scale)
        size = (max(1, int(160 * scale)), max(1, int(96 * scale)))
        self.photo = ImageTk.PhotoImage(image.resize(size, Image.Resampling.NEAREST))
        self.canvas.delete('all')
        self.canvas.create_image(width // 2, height // 2, image=self.photo)

    def resize_preview(self, event):
        if self.current_frame:
            self.show_image(self.current_frame)
        elif self.tab == 'gif':
            self._draw_canvas_placeholder(t('GIF önizlemesi'))

    def build_nowbar_media(self, mode_override=None, clock_override=None):
        layout = self.effective_layout()
        theme = self.current_theme_key()
        label = self.label_var.get()
        note = self.note_var.get()
        mode = self.effective_mode(mode_override)
        clock_str = clock_override or datetime.now().strftime('%H:%M')
        interval_key = self.current_sync_interval_key()
        media_data = {
            **self.info,
            'hide_elapsed': mode == 'device_loop' or interval_key == 'event',
            'bg_image_path': self.bg_image_path,
        }
        if mode == 'device_loop':
            render_mode, frame_count = 'device_loop', 96
        elif mode == 'fast_anim':
            render_mode, frame_count = 'animated', 8
        elif mode == 'animated':
            render_mode, frame_count = 'animated', 16
        else:
            render_mode, frame_count = 'static', 1
        frames, durations = render_nowbar_frames(
            layout, media_data, self.stats, theme_key=theme,
            label=label, custom_note=note, mode=render_mode, frame_count=frame_count, clock=clock_str,
        )
        title_part = t(LAYOUTS.get(layout, 'Now Bar')).split(' (')[0]
        payload = {'name': f'Now Bar - {title_part}', 'frames': frames, 'durations': durations, 'clock': clock_str}
        if mode == 'device_loop':
            payload['preview_key'] = (
                get_language(), mode, interval_key, layout, theme, label, note, self.bg_image_path,
                self.info.get('available'), self.info.get('title'), self.info.get('artist'),
                self.info.get('playing'), self.info.get('source'), self.info.get('cover_hash', ''), (),
            )
        return payload

    def render_nowbar_preview_now(self):
        if self.state() == 'withdrawn':
            return
        layout = self.effective_layout()
        theme = self.current_theme_key()
        label = self.label_var.get()
        note = self.note_var.get()
        mode = self.effective_mode()
        clock_str = datetime.now().strftime('%H:%M')
        interval_key = self.current_sync_interval_key()
        hide_elapsed = mode == 'device_loop' or interval_key == 'event'
        pos_bucket = 0 if hide_elapsed else int(float(self.info.get('position', 0) or 0) // 2)
        # A device loop is a snapshot. Keep its desktop preview on the same
        # frames until metadata or design changes, just as the keyboard does.
        changing_values = () if mode == 'device_loop' else (
            pos_bucket, self.stats.get('cpu'), self.stats.get('ram'), clock_str,
        )
        key = (get_language(), mode, interval_key, layout, theme, label, note, self.bg_image_path,
               self.info.get('available'), self.info.get('title'), self.info.get('artist'),
               self.info.get('playing'), self.info.get('source'), self.info.get('cover_hash', ''),
               changing_values)
        if self.cached_nowbar_key != key or not self.cached_nowbar_frames:
            payload = self.build_nowbar_media(clock_override=clock_str)
            self.cached_nowbar_frames = payload['frames']
            self.cached_nowbar_durations = payload['durations']
            self.cached_nowbar_key = key
            self.preview_anim_step = 0
        idx = self.preview_anim_step % len(self.cached_nowbar_frames)
        self.show_image(self.cached_nowbar_frames[idx])
        self._preview_delay = (
            self.cached_nowbar_durations[idx] if mode != 'static' else 500
        )

        media_txt = (
            f"{t('Çalıyor') if self.info.get('playing') else t('Duraklatıldı')}: {self.info.get('title', '')}"
            if self.info.get('available') else t('Aktif medya yok')
        )
        self.details.configure(
            text=f"{media_txt}   |   CPU {self.stats.get('cpu', 0)}%  ·  RAM {self.stats.get('ram', 0)}% "
                 f"({self.stats.get('used', '0')}/{self.stats.get('total', '0')} GB)"
                 + (t('   |   Cihaz döngüsü: saat/sistem aktarım anıdır.') if mode == 'device_loop' else '')
        )

    def animate(self):
        delay = 120
        if self.tab == 'nowbar' and self.state() != 'withdrawn':
            mode = self.effective_mode()
            self.render_nowbar_preview_now()
            delay = self._preview_delay
            if mode != 'static' and self.cached_nowbar_frames:
                self.preview_anim_step = (self.preview_anim_step + 1) % len(self.cached_nowbar_frames)
        elif self.tab == 'gif' and self.media and self.state() != 'withdrawn':
            self.frame_index %= len(self.media['frames'])
            self.show_image(self.media['frames'][self.frame_index])
            delay = self.media['durations'][self.frame_index]
            self.frame_index += 1
        elif self.state() == 'withdrawn':
            delay = 1000
        self.after(delay, self.animate)

    def refresh_telemetry(self):
        if self._closing or self._quit_after_upload:
            return
        if getattr(self, '_demo', False):
            return
        self.stats = system_stats()
        if self.media_future and self.media_future.done():
            try:
                self.info = self.media_future.result()
                self.last_error = ''
            except Exception as error:
                self.last_error = str(error)
            self.media_future = None
        if not self.media_future:
            self.media_future = self.media_executor.submit(lambda: asyncio.run(media_info()))
        if self.tab == 'nowbar':
            self.maybe_auto_sync()
        self.after(1000, self.refresh_telemetry)

    def refresh_usb_status(self):
        if self._closing or self._quit_after_upload:
            return
        if getattr(self, '_demo', False):
            self.usb_message = t('Demo önizleme · cihaz erişimi yok')
            self.usb_label.configure(text=self.usb_message, fg=ACCENT)
            return
        if not self.uploading:
            was_connected = self.usb_connected
            ok, msg = check_connection()
            self.usb_connected = ok
            self.usb_message = msg
            self.usb_label.configure(text=t(msg), fg=SUCCESS if ok else WARN)
            if ok and not was_connected:
                # A reconnected device may have rebooted or changed its display.
                self.last_sync_signature = None
                self.last_sync_clock = ''
                self._retry_failures = 0
                self._next_retry_at = 0.0
            if ok and self.tab == 'nowbar':
                self.maybe_auto_sync()
        self.after(3000, self.refresh_usb_status)

    def maybe_auto_sync(self, force=False):
        if (getattr(self, '_demo', False) or self._closing or self._quit_after_upload or not self.auto_sync_var.get()
                or self.tab != 'nowbar' or self.uploading or not self.usb_connected):
            return
        if not force and time.monotonic() < self._next_retry_at:
            return
        playing_active = self.is_media_playing()
        layout = self.effective_layout()
        eff_mode = self.effective_mode()
        interval_key = self.current_sync_interval_key()
        clock_hm = datetime.now().strftime('%H:%M')
        cpu = int(self.stats.get('cpu', 0))
        ram = int(self.stats.get('ram', 0))
        event_sig = (
            get_language(),
            layout,
            self.current_theme_key(),
            self.label_var.get(),
            self.note_var.get(),
            self.bg_image_path,
            eff_mode,
            interval_key,
            bool(self.idle_clock_sync_var.get()),
            bool(self.info.get('available')),
            playing_active,
            self.info.get('title', ''),
            self.info.get('artist', ''),
            self.info.get('source', ''),
            self.info.get('cover_hash', ''),
        )
        event_changed = force or (event_sig != self.last_sync_signature)
        clock_changed = (clock_hm != self.last_sync_clock)
        device_loop = eff_mode == 'device_loop'
        clock_should_sync = not device_loop and clock_changed and (
            interval_key == '1m'
            or (not playing_active and self.idle_clock_sync_var.get())
        )
        should_sync = event_changed or clock_should_sync
        elapsed = time.monotonic() - self.last_sync_time
        last_cpu, last_ram = self.last_sync_stats
        if not should_sync and not device_loop:
            if interval_key == '30s' and elapsed >= 30.0:
                should_sync = True
            else:
                stat_jump = (
                    abs(cpu - last_cpu) >= 30
                    or abs(ram - last_ram) >= 8
                    or (ram >= 85 and last_ram < 85)
                )
                if stat_jump and elapsed >= 45.0:
                    should_sync = True

        if should_sync:
            payload = self.build_nowbar_media(mode_override=eff_mode, clock_override=clock_hm)
            self.last_sync_signature = event_sig
            self.last_sync_clock = payload['clock']
            self.last_sync_stats = (cpu, ram)
            self.last_sync_time = time.monotonic()
            self._start_usb_upload(payload, is_auto=True)

    def selected_media(self):
        if self.tab == 'gif':
            if not self.media:
                raise ValueError(t('Önce bir GIF seç.'))
            return self.media
        return self.build_nowbar_media()

    def upload_usb_clicked(self):
        if getattr(self, '_demo', False):
            self.status_var.set(t('Demo modunda klavyeye veri gönderilmez.'))
            return
        if self.uploading:
            return
        try:
            payload = self.selected_media()
        except Exception as error:
            messagebox.showerror(t('Hazırlanamadı'), str(error))
            return
        self._start_usb_upload(payload, is_auto=False)

    def _start_usb_upload(self, payload, is_auto=False):
        if getattr(self, '_demo', False) or self.uploading or self._closing or self._quit_after_upload:
            return
        if payload.get('preview_key') is not None:
            # Reuse the exact uploaded snapshot when the window is restored;
            # a new clock/system reading must not alter the desktop preview.
            self.cached_nowbar_frames = payload['frames']
            self.cached_nowbar_durations = payload['durations']
            self.cached_nowbar_key = payload['preview_key']
            self.preview_anim_step = 0
        self.uploading = True
        self.upload_btn.configure(state='disabled')
        self.progress_var.set(0)
        count = len(payload['frames'])
        prefix = 'Auto-Sync' if is_auto else t('USB aktarımı')
        self.status_var.set(t('{prefix}: {count} kare klavyeye gönderiliyor…', prefix=prefix, count=count))

        # The USB worker must never call Tk. Closing a window or a Tcl error
        # cannot be allowed to interrupt the device transaction before commit.
        progress_updates = queue.SimpleQueue()

        def on_progress(pct):
            progress_updates.put(pct)

        def task():
            with Keyboard() as kb:
                return kb.upload(payload['frames'], payload['durations'], slot=1, progress=on_progress, select=False)

        self.upload_future = self.upload_executor.submit(task)

        def poll():
            while True:
                try:
                    self.progress_var.set(progress_updates.get_nowait())
                except queue.Empty:
                    break
            if not self.upload_future.done():
                self.after(80, poll)
                return
            self.uploading = False
            self.last_sync_time = time.monotonic()
            self.upload_btn.configure(state='normal')
            try:
                res = self.upload_future.result()
                self._retry_failures = 0
                self._next_retry_at = 0.0
                self.progress_var.set(100)
                stamp = datetime.now().strftime('%H:%M:%S')
                self.status_var.set(
                    t('Klavyeye yüklendi ({time}) · {frames} kare, {pages} sayfa (Slot {slot}).',
                      time=stamp, frames=res['frames'], pages=res['pages'], slot=res['slot'])
                )
                if not self._quit_after_upload:
                    self.after(200, self.maybe_auto_sync)
            except Exception as error:
                self.progress_var.set(0)
                self.last_sync_signature = None
                self.last_sync_clock = ''
                self._retry_failures += 1
                retry_delay = min(60.0, 5.0 * 2 ** min(self._retry_failures - 1, 4))
                self._next_retry_at = time.monotonic() + retry_delay
                err_msg = str(error)
                self.status_var.set(t('USB yükleme hatası: {error} · Otomatik deneme {seconds} sn sonra.',
                                      error=err_msg, seconds=int(retry_delay)))
                if not is_auto and not self._quit_after_upload:
                    messagebox.showerror(t('Klavyeye Yüklenemedi'), err_msg)
            if self._quit_after_upload:
                self.quit_completely()

        self.after(80, poll)

    def pick_gif(self):
        if self.gif_busy:
            return
        path = filedialog.askopenfilename(title=t('Bir GIF seç'), filetypes=[(t('GIF animasyonu'), '*.gif')])
        if path:
            self.load_gif(Path(path))

    def load_gif(self, path):
        if self.gif_busy:
            return
        self.original_path = path
        self.gif_busy = True
        self.status_var.set(t('GIF hazırlanıyor…'))
        self.update_idletasks()
        future = self.gif_executor.submit(prepare_gif, path, self.fit_var.get())

        def finish():
            if not future.done():
                self.after(80, finish)
                return
            self.gif_busy = False
            try:
                self.media = future.result()
                self.switch_tab('gif')
                self.frame_index = 0
                m = self.media
                self.details.configure(
                    text=t('{name}  ·  {source} → {count} kare  ·  {seconds:.1f} sn',
                           name=path.name, source=m['source_frames'], count=len(m['frames']), seconds=m['duration']/1000)
                )
                warning = t(' Uzun animasyonun tamamından 255 kare seçildi.') if m['source_frames'] > 255 else ''
                timing = t(' Klavye sınırları nedeniyle süre değişti.') if abs(m['source_duration'] - m['duration']) > 50 else ''
                self.status_var.set(t('GIF hazır. Doğrudan USB ile yükleyebilir veya HAVIT kütüphanesine ekleyebilirsin.') + warning + timing)
            except Exception as error:
                messagebox.showerror(t('GIF hazırlanamadı'), str(error))
                self.status_var.set(t('Başka bir GIF seçebilirsin.'))

        self.after(80, finish)

    def refit_gif(self):
        if self.original_path and not self.gif_busy:
            self.load_gif(self.original_path)

    def export(self):
        try:
            media = self.selected_media()
            safe = ''.join(c for c in media['name'] if c not in '<>:"/\\|?*')
            path = filedialog.asksaveasfilename(
                title=t('Uyumlu GIF’i kaydet'), defaultextension='.gif',
                initialfile=f'KB884L-{safe}.gif', filetypes=[('GIF', '*.gif')],
            )
            if path:
                save_gif(media, path)
                self.status_var.set(t('Kaydedildi: ') + path)
        except Exception as error:
            messagebox.showerror(t('Kaydedilemedi'), str(error))

    def register(self):
        if getattr(self, '_demo', False):
            self.status_var.set(t('Demo modunda HAVIT kütüphanesi değiştirilmez.'))
            return
        try:
            media = self.selected_media()
            result = add_to_driver(media)
            self.status_var.set(t('{count} kare HAVIT kütüphanesine eklendi (ID {id}).',
                                  count=len(media['frames']), id=result['led_id']))
            messagebox.showinfo(
                t('Kütüphaneye Eklendi'),
                t('{count} kare HAVIT kütüphanesine eklendi.\n\nHAVIT yazılımını sistem tepsisinden Çıkış yapıp yeniden açarak TFT sekmesinden görebilirsin.\n\nYedek:\n{backup}',
                  count=len(media['frames']), backup=result['backup']),
            )
        except Exception as error:
            messagebox.showerror(t('Eklenemedi'), str(error))

    def _listen_ipc(self):
        while self.ipc_sock is not None:
            try:
                data, _addr = self.ipc_sock.recvfrom(64)
            except OSError:
                break
            cmd = data.strip().upper()
            if cmd == b'SHOW':
                self.after(0, self.restore_window)
            elif cmd == b'QUIT':
                self.after(0, self.quit_completely)
                break

    def restore_window(self):
        self.deiconify()
        self.state('normal')
        self.lift()
        self.focus_force()
        if self.tab == 'nowbar':
            self.render_nowbar_preview_now()

    def hide_to_tray(self):
        if getattr(self, '_demo', False):
            self.status_var.set(t('Demo modu: USB, ağ, başlangıç ve ayar kaydı kapalı.'))
            return
        self.persist_settings()
        self.withdraw()
        self.status_var.set(t('Sistem tepsisinde arka planda çalışıyor — ikona tıklayarak geri açabilirsiniz.'))

    def on_window_close(self):
        self.persist_settings()
        if self.bg_close_var.get() and not self._demo:
            self.hide_to_tray()
        else:
            self.quit_completely()

    def quit_completely(self):
        if self._closing:
            return
        if self.uploading:
            self._quit_after_upload = True
            self.status_var.set(t('Devam eden klavye aktarımı tamamlanınca program kapanacak…'))
            return
        self._closing = True
        self.persist_settings()
        tray, self.tray = getattr(self, 'tray', None), None
        if tray is not None:
            tray.stop()
        sock, self.ipc_sock = self.ipc_sock, None
        if sock is not None:
            try:
                sock.close()
            except OSError:
                pass
        for ex in (self.media_executor, self.upload_executor, self.gif_executor):
            ex.shutdown(wait=False, cancel_futures=True)
        self.destroy()

    def close(self):
        self.quit_completely()


def run_self_test(output_dir: Path):
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    output_dir.mkdir(parents=True, exist_ok=True)
    info = asyncio.run(media_info())
    stats = system_stats()
    usb_ok, usb_msg = check_connection()

    layouts_tested = []
    for key in LAYOUTS:
        img = render_nowbar(key, info, stats, theme_key='cover', label='STUDIO', custom_note=t('Hazır · Now Bar'))
        assert img.size == (160, 96), f'Unexpected size for {key}: {img.size}'
        img.save(output_dir / f'{key}.png')
        layouts_tested.append(key)

    # Verify synthetic artwork rendering + dynamic palette even when idle
    sample_cover = Image.new('RGB', (64, 64), '#1a1230')
    for y in range(64):
        for x in range(64):
            sample_cover.putpixel((x, y), (min(255, 60 + x * 3), 45 + (y * 2) % 120, max(40, 230 - y * 2)))
    sample_hash = register_cover_image(sample_cover)
    sample_media = {
        'available': True, 'playing': True, 'title': 'In Pieces', 'artist': 'Linkin Park',
        'position': 95.0, 'duration': 218.0, 'source': 'Spotify',
        'has_cover': True, 'cover_hash': sample_hash, 'hide_elapsed': True,
    }
    artwork_img = render_nowbar('nowbar_artwork', sample_media, stats, theme_key='cover', label='STUDIO', phase=0.35)
    assert artwork_img.size == (160, 96)
    artwork_img.save(output_dir / 'nowbar_artwork_sample.png')

    # Verify redesigned Glass İkili Now Bar with custom background wallpaper
    sample_bg = Image.new('RGB', (160, 96), '#102030')
    for y in range(96):
        for x in range(160):
            sample_bg.putpixel((x, y), (min(255, 30 + x), min(255, 50 + y * 2), 180))
    dual_bg_img = render_nowbar(
        'nowbar_dual',
        {'available': False, 'bg_image': sample_bg},
        stats,
        theme_key='galaxy',
        label='STUDIO',
        custom_note=t('Hazır · Masaüstü'),
    )
    assert dual_bg_img.size == (160, 96)
    dual_bg_img.save(output_dir / 'nowbar_dual_bg_sample.png')

    anim_frames, anim_durations = render_nowbar_frames(
        'nowbar_carousel', info, stats, theme_key='cover', label='STUDIO',
        custom_note=t('Hazır · Now Bar'), animated=True, frame_count=16,
    )
    assert len(anim_frames) == 16 and len(anim_durations) == 16
    assert all(f.size == (160, 96) for f in anim_frames)
    save_gif({'frames': anim_frames, 'durations': anim_durations}, output_dir / 'nowbar_animated.gif')

    timeline_frames, timeline_durations = render_nowbar_frames(
        'nowbar_dual', info, stats, theme_key='cover', label='STUDIO',
        custom_note=t('Hazır · Now Bar'), mode='timeline', frame_count=10,
    )
    assert len(timeline_frames) == 10 and len(timeline_durations) == 10
    assert all(f.size == (160, 96) for f in timeline_frames)
    save_gif({'frames': timeline_frames, 'durations': timeline_durations}, output_dir / 'nowbar_timeline.gif')

    loop_counts = {}
    for layout in LAYOUTS:
        loop_frames, loop_delays = render_nowbar_frames(
            layout, sample_media, stats, theme_key='cover', label='STUDIO',
            custom_note=t('Hazır · Now Bar'), mode='device_loop', frame_count=96)
        assert 2 <= len(loop_frames) <= 96
        assert len(loop_frames) == len(loop_delays)
        assert all(f.size == (160, 96) for f in loop_frames)
        assert all(30 <= d <= 500 and d % 2 == 0 for d in loop_delays)
        loop_counts[layout] = len(loop_frames)
        if layout == 'nowbar_media':
            save_gif({'frames': loop_frames, 'durations': loop_delays},
                     output_dir / 'nowbar_device_loop.gif')

    report = {
        'size': [160, 96],
        'media_read': bool(info.get('title')),
        'media_available': bool(info.get('available')),
        'media_title': info.get('title'),
        'has_cover': bool(info.get('has_cover')),
        'system_stats': stats,
        'usb_connected': usb_ok,
        'usb_status': usb_msg,
        'layouts_tested': layouts_tested,
        'artwork_cover_tested': True,
        'dual_bg_tested': True,
        'animated_frames': len(anim_frames),
        'timeline_frames': len(timeline_frames),
        'device_loop_layouts': loop_counts,
    }
    (output_dir / 'result.json').write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding='utf-8')
    print(json.dumps(report, indent=2, ensure_ascii=False))


def run_upload_nowbar():
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    info = asyncio.run(media_info())
    stats = system_stats()
    frames, durations = render_nowbar_frames(
        'nowbar_dual', {**info, 'hide_elapsed': True}, stats, theme_key='cover', label='STUDIO',
        custom_note=t('Hazır · Now Bar'), mode='static',
    )
    events = []
    with Keyboard(logger=events.append) as kb:
        upload_res = kb.upload(frames, durations, slot=1, select=False)
    result = {
        'upload': upload_res,
        'media': info,
        'stats': stats,
        'events': events,
    }
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == '__main__':
    args = sys.argv[1:]
    language = None
    if '--lang' in args:
        index = args.index('--lang')
        if index + 1 >= len(args) or args[index + 1] not in LANGUAGES:
            raise SystemExit('--lang must be en or tr')
        language = args[index + 1]
        args = args[:index] + args[index + 2:]
        set_language(language)
    if args and args[0] == '--self-test':
        target = Path(args[1]) if len(args) > 1 else Path('nowbar-test')
        run_self_test(target)
    elif args and args[0] == '--upload-nowbar':
        run_upload_nowbar()
    elif args and args[0] == '--quit':
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                s.sendto(b'QUIT', (IPC_HOST, IPC_PORT))
        except OSError:
            pass
    elif '--demo' in args:
        # This branch does not bind IPC or touch an existing running Studio.
        Studio(demo=True, language=language or 'en').mainloop()
    else:
        start_hidden = '--background' in args
        ipc = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            ipc.bind((IPC_HOST, IPC_PORT))
        except OSError:
            if not start_hidden:
                try:
                    ipc.sendto(b'SHOW', (IPC_HOST, IPC_PORT))
                except OSError:
                    pass
            ipc.close()
            sys.exit(0)
        Studio(ipc_sock=ipc, start_hidden=start_hidden, language=language,
               file_paths=[a for a in args if not a.startswith('--')]).mainloop()
