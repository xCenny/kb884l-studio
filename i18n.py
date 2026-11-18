"""Small, dependency-free English/Turkish message catalogue.

Internal layout/theme IDs never depend on the selected language. Modules may
register their own messages without importing UI code or opening any devices.
"""
from __future__ import annotations

LANGUAGES = {'en': 'English', 'tr': 'Türkçe'}
_language = 'en'
_EN: dict[str, str] = {
    'Medya bekleniyor': 'Waiting for media',
    'Spotify veya tarayıcıda oynat': 'Play in Spotify or a browser',
    'USB kontrol ediliyor…': 'Checking USB…',
    'Sadece Şarkı/Durum Değişiminde': 'On track / status changes only',
    'Her 1 Dakikada Bir (Saat + Şarkı Değişimi)': 'Every minute + track changes',
    'Her 30 Saniyede Bir': 'Every 30 seconds',
    'Varsayılan Gradyan': 'Default gradient',
    'Now Bar arayüzünü özelleştir ve tek tıkla USB’den klavyeye gönder.': 'Design your Now Bar, preview it, then upload over USB.',
    'Now Bar Ekran Studio': 'Now Bar Screen Studio',
    '160 × 96 TFT-LCD  ·  Doğrudan USB HID ekran özelleştirme': '160 × 96 TFT-LCD  ·  Direct USB HID screen customization',
    'Başlangıç & Sistem Tepsisi': 'Startup & system tray',
    'Bilgisayar Açıldığında Otomatik Başlat': 'Launch with Windows',
    'Kapatınca (X) Sistem Tepsisine Küçült': 'Close (X) to system tray',
    'Şimdi Tepsiye Gizle': 'Hide to tray',
    'Now Bar Tasarımcısı': 'Now Bar designer',
    'Özel GIF Hazırlama': 'Custom GIF',
    'Now Bar Önizlemesi': 'Now Bar preview',
    'Medya, saat, CPU ve RAM bilgilerini 160×96 tuvalde önizle. Klavye güncellemeleri görüntü yüklemesi gerektirir.': 'Preview media, clock, CPU and RAM on a 160×96 canvas. Changes require an image upload to the keyboard.',
    'Sistem ve medya okunuyor…': 'Reading system and media…',
    'Doğrudan Klavyeye Yükle (USB)': 'Upload to keyboard (USB)',
    'Otomatik Görüntü Aktarımı (Auto-Sync)': 'Automatic image upload (Auto-Sync)',
    'HAVIT’e Ekle': 'Add to HAVIT',
    'GIF Kaydet': 'Save GIF',
    'Tamamen Çıkış': 'Quit',
    'Now Bar Düzeni': 'Now Bar layout',
    'Oynatma Başlayınca Otomatik Vitrin Now Bar’a Geç': 'Switch to artwork layout during playback',
    'Görünüm & Arka Plan': 'Appearance & wallpaper',
    'Renk Teması': 'Color theme',
    'Arka Plan Görseli Seç…': 'Choose wallpaper…',
    'Arka Plan Görseli Seç': 'Choose wallpaper',
    'Kaldır': 'Remove',
    'Üst Etiket': 'Label',
    'Boşta Durum Yazısı': 'Idle message',
    'Çalışma Modu & Yenileme': 'Animation & refresh',
    'Anlık Kart (1 Kare - ~1 sn En Hızlı Geçiş)': 'Static card (1 frame · fastest upload)',
    'Hızlı Animasyon (8 Kare - Ekolayzır & Kayan Yazı)': 'Short animation (8 frames)',
    'Tam Animasyon (16 Kare - Dönüşümlü & Uzun Akış)': 'Full animation (16 frames)',
    'Akıcı cihaz döngüsü (96 kareye kadar · Tek yükleme)': 'Stored loop (up to 96 frames · one upload)',
    'Klavye döngüyü kendi oynatır; şarkı veya tasarım değişince yeniden aktarılır.\nBu modda saat ve sistem değerleri aktarım anını gösterir.': 'The keyboard replays the stored loop. Track or design changes require a new upload.\nClock and system values are snapshots from upload time.',
    'Otomatik Yenileme Sıklığı': 'Automatic refresh interval',
    'Şarkı Çalmıyorken Saat Değişiminde Yenile': 'Refresh the clock while media is idle',
    'GIF Seç (.gif)': 'Choose GIF (.gif)',
    'Ekrana Yerleştirme': 'Fit to screen',
    'Tamamı görünsün': 'Contain · show the whole image',
    'Ekranı doldur / kenarları kırp': 'Cover · fill the screen and crop edges',
    'Doğrudan USB Aktarımı': 'Direct USB upload',
    'Hazırlanan GIF kareleri doğrudan USB üzerinden klavyeye yüklenebilir veya HAVIT veritabanına eklenebilir. Doğrudan USB aktarımı sırasında HAVIT yazılımının kapalı olması gerekir.': 'Prepared frames can be uploaded over USB or added to the HAVIT library. Fully quit the HAVIT app before a direct USB upload. The keyboard may show its loading screen during transfers.',
    'Windows başlangıcında arka planda çalışacak.': 'Studio will launch in the background with Windows.',
    'Windows otomatik başlatma kaldırıldı.': 'Launch with Windows is disabled.',
    'İkili Now Bar Arka Plan Görseli Seç': 'Choose a Dual Now Bar wallpaper',
    'Görsel Dosyaları': 'Image files',
    'Görsel Yüklenemedi': 'Unable to load image',
    'Seçilen görsel dosyası açılamadı.': 'The selected image could not be opened.',
    'Arka plan görseli temizlendi.': 'Wallpaper removed.',
    'Otomatik görüntü aktarımı açıldı. Yenilemeler klavyenin yükleme ekranını gösterebilir.': 'Automatic image upload enabled. Refreshes can show the keyboard loading screen.',
    'Otomatik görüntü aktarımı kapatıldı.': 'Automatic image upload disabled.',
    'GIF’i Bir Kez Seç': 'Choose one GIF',
    'Kareler, 160×96 boyut ve saydamlık otomatik düzenlenir; 255 kareye kadar desteklenir.': 'Frames, transparency and the 160×96 fit are prepared automatically. Up to 255 frames.',
    'Henüz GIF seçilmedi': 'No GIF selected yet',
    'GIF önizlemesi': 'GIF preview',
    'Çalıyor': 'Playing',
    'Duraklatıldı': 'Paused',
    'Aktif medya yok': 'No active media',
    '   |   Cihaz döngüsü: saat/sistem aktarım anıdır.': '   |   Stored loop: clock/system are upload-time snapshots.',
    'Önce bir GIF seç.': 'Choose a GIF first.',
    'Hazırlanamadı': 'Unable to prepare',
    'USB aktarımı': 'USB upload',
    'Klavyeye Yüklenemedi': 'Upload failed',
    'Bir GIF seç': 'Choose a GIF',
    'GIF animasyonu': 'GIF animation',
    'GIF hazırlanıyor…': 'Preparing GIF…',
    ' Uzun animasyonun tamamından 255 kare seçildi.': ' Sampled 255 frames across the full animation.',
    ' Klavye sınırları nedeniyle süre değişti.': ' Timing was adjusted to fit the keyboard limits.',
    'GIF hazır. Doğrudan USB ile yükleyebilir veya HAVIT kütüphanesine ekleyebilirsin.': 'GIF ready. Upload over USB or add it to the HAVIT library.',
    'GIF hazırlanamadı': 'Unable to prepare GIF',
    'Başka bir GIF seçebilirsin.': 'Try another GIF.',
    'Uyumlu GIF’i kaydet': 'Save compatible GIF',
    'Kaydedildi: ': 'Saved: ',
    'Kaydedilemedi': 'Unable to save',
    'Kütüphaneye Eklendi': 'Added to library',
    'Eklenemedi': 'Unable to add',
    'Sistem tepsisinde arka planda çalışıyor — ikona tıklayarak geri açabilirsiniz.': 'Running in the tray. Click the icon to reopen Studio.',
    'Devam eden klavye aktarımı tamamlanınca program kapanacak…': 'Studio will quit when the current keyboard upload finishes…',
    'Hazır · Now Bar': 'Ready · Now Bar',
    'Hazır · Masaüstü': 'Ready · Desktop',
    'Dil': 'Language',
    'Dili değiştirmeden önce aktarımın bitmesini bekle.': 'Wait for the current operation before changing language.',
    'Dil değiştirildi.': 'Language changed.',
    'Demo önizleme · cihaz erişimi yok': 'Demo preview · no device access',
    'Demo modu: USB, ağ, başlangıç ve ayar kaydı kapalı.': 'Demo mode: USB, network, startup changes and settings writes are disabled.',
    'Demo modunda klavyeye veri gönderilmez.': 'Demo mode does not send data to the keyboard.',
    'Demo modunda HAVIT kütüphanesi değiştirilmez.': 'Demo mode does not modify the HAVIT library.',
    'Arka plan görseli seçildi: {name}': 'Wallpaper selected: {name}',
    '{name}  ·  {source} → {count} kare  ·  {seconds:.1f} sn': '{name}  ·  {source} → {count} frames  ·  {seconds:.1f} s',
    '{prefix}: {count} kare klavyeye gönderiliyor…': '{prefix}: uploading {count} frames…',
    'Klavyeye yüklendi ({time}) · {frames} kare, {pages} sayfa (Slot {slot}).': 'Uploaded ({time}) · {frames} frames, {pages} pages (slot {slot}).',
    'USB yükleme hatası: {error} · Otomatik deneme {seconds} sn sonra.': 'USB upload error: {error} · Retrying in {seconds} s.',
    '{count} kare HAVIT kütüphanesine eklendi (ID {id}).': 'Added {count} frames to the HAVIT library (ID {id}).',
    '{count} kare HAVIT kütüphanesine eklendi.\n\nHAVIT yazılımını sistem tepsisinden Çıkış yapıp yeniden açarak TFT sekmesinden görebilirsin.\n\nYedek:\n{backup}': 'Added {count} frames to the HAVIT library.\n\nFully quit and reopen the HAVIT app, then open its TFT tab.\n\nBackup:\n{backup}',
}


def register_translations(mapping: dict[str, str]) -> None:
    """Register another module's English catalogue."""
    _EN.update(mapping)


def get_language() -> str:
    return _language


def set_language(language: str) -> str:
    global _language
    _language = language if language in LANGUAGES else 'en'
    return _language


def t(text: str, **values) -> str:
    """Translate a literal message and format named values in either locale."""
    result = _EN.get(text, text) if _language == 'en' else text
    return result.format(**values) if values else result
