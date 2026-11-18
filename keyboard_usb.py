"""KB884L screen protocol, verified against this unit's vendor executable.

Only the LCD upload (0x72) and clock/page selection (0x28) transactions are
exposed. No firmware, keymap, reset, or arbitrary-command interface is provided.
"""
from __future__ import annotations
import hashlib
import ctypes
from ctypes import wintypes
import json
import struct
import threading
import time
from datetime import datetime
from pathlib import Path
import hid
from i18n import t
import i18n_backend

VID, PID, RELEASE = 0x05AC, 0x024F, 0x0111
SIZE = (160, 96)
MAX_FRAMES = 255
PAGE_SIZE = 4096
DESCRIPTORS = {
    2: bytes.fromhex('0668ff0961a1010962150026ff007508954081020963150026ff0075089600109102c0'),
    3: bytes.fromhex('0613ff0901a1010902150026ff007508954081020903150026ff007508954091020a00ff150026ff0075089540b102c0'),
}
_LOCK=threading.Lock()
_PROCESS_MUTEX_NAME = r'Local\KB884LStudio.ScreenUSB.05AC024F'
_TRANSACTION_WAIT_SECONDS = 5.0

_kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
_kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
_kernel32.CreateMutexW.restype = wintypes.HANDLE
_kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
_kernel32.WaitForSingleObject.restype = wintypes.DWORD
_kernel32.ReleaseMutex.argtypes = [wintypes.HANDLE]
_kernel32.ReleaseMutex.restype = wintypes.BOOL
_kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
_kernel32.CloseHandle.restype = wintypes.BOOL

class KeyboardError(Exception): pass


class _ProcessMutex:
    """Serialize complete screen transactions across Studio/CLI processes.

    Windows grants ownership for WAIT_ABANDONED as well as WAIT_OBJECT_0.
    The caller can then begin a fresh transaction; no reset/firmware command
    is sent by this lock. Handles and ownership are released on every path.
    """
    def __init__(self, name=None):
        self.handle = _kernel32.CreateMutexW(None, False, name or _PROCESS_MUTEX_NAME)
        self.owned = False
        self.abandoned = False
        if not self.handle:
            raise KeyboardError(t('USB aktarım kilidi oluşturulamadı: ') + str(ctypes.WinError(ctypes.get_last_error())))

    def acquire(self, timeout_ms=5000):
        if not self.handle:
            raise KeyboardError(t('USB aktarım kilidi kapalı.'))
        if self.owned:
            raise KeyboardError(t('USB aktarım kilidi zaten alındı.'))
        result = _kernel32.WaitForSingleObject(self.handle, max(0, int(timeout_ms)))
        if result in (0, 0x80):
            self.owned = True
            self.abandoned = result == 0x80
            return self
        error = ctypes.get_last_error()
        self.close()
        if result == 0x102:
            raise KeyboardError(t('Klavyeye başka bir Studio işlemi veri gönderiyor. Aktarımın bitmesini bekle.'))
        raise KeyboardError(t('USB aktarım kilidi alınamadı: ') + str(ctypes.WinError(error)))

    def close(self):
        if self.handle:
            try:
                if self.owned:
                    if not _kernel32.ReleaseMutex(self.handle):
                        raise KeyboardError(t('USB aktarım kilidi bırakılamadı: ') + str(ctypes.WinError(ctypes.get_last_error())))
            finally:
                _kernel32.CloseHandle(self.handle)
                self.handle = None
                self.owned = False

    def __enter__(self):
        return self.acquire()

    def __exit__(self, *_args):
        self.close()

def discover():
    devices=hid.enumerate(VID,PID)
    matches={}
    for interface,usage in ((2,0xff68),(3,0xff13)):
        found=[d for d in devices if d.get('interface_number')==interface and d.get('usage_page')==usage
               and d.get('release_number')==RELEASE and d.get('manufacturer_string')=='SONiX'
               and d.get('product_string')=='Gaming Keyboard']
        if len(found)!=1:
            raise KeyboardError(t('KB884L USB bağlantısı bulunamadı veya birden çok aynı cihaz bağlı.'))
        matches[interface]=found[0]
    # Reject interfaces belonging to different physical instances.
    if matches[2]['path'].lower().split(b'&mi_')[0]!=matches[3]['path'].lower().split(b'&mi_')[0]:
        raise KeyboardError(t('USB arayüzleri aynı klavyeye ait değil.'))
    return matches

def check_connection():
    """Return (connected, status_message) for the attached KB884L unit."""
    try:
        discover()
        return True, t('USB Bağlı: KB884L-TUR (05AC:024F)')
    except KeyboardError as err:
        return False, str(err)
    except Exception as err:
        return False, t('USB kontrol hatası: {error}', error=err)

def rgb565(image):
    if image.size!=SIZE:raise ValueError(t('Görüntü 160×96 piksel olmalı.'))
    raw=image.convert('RGB').tobytes(); result=bytearray(160*96*2)
    for source,target in zip(range(0,len(raw),3),range(0,len(result),2)):
        red,green,blue=raw[source:source+3]
        value=((red&0xf8)<<8)|((green&0xfc)<<3)|(blue>>3)
        result[target]=value&0xff; result[target+1]=value>>8
    return bytes(result)

def build_buffer(frames,durations):
    if not 1<=len(frames)<=MAX_FRAMES or len(frames)!=len(durations):
        raise ValueError(t('Geçersiz animasyon kareleri.'))
    header=bytearray(b'\xff'*256); header[0]=len(frames)
    for index,duration in enumerate(durations):
        if not 2<=duration<=510:raise ValueError(t('Kare süresi 2–510 ms arasında olmalı.'))
        header[index+1]=min(255,max(1,int(duration)//2))
    raw=bytes(header)+b''.join(rgb565(frame) for frame in frames)
    pages=(len(raw)+PAGE_SIZE-1)//PAGE_SIZE
    return raw.ljust(pages*PAGE_SIZE,b'\xff')

class Keyboard:
    def __init__(self,logger=None):
        self.ctrl=None;self.lcd=None;self.logger=logger
        self._process_mutex=None;self._local_lock_held=False
    def log(self,event,**fields):
        if self.logger:self.logger({'time':datetime.now().isoformat(),'event':event,**fields})
    def __enter__(self):
        if self._local_lock_held:
            raise KeyboardError(t('Aynı USB aktarım bağlamı yeniden açılamaz.'))
        deadline = time.monotonic() + _TRANSACTION_WAIT_SECONDS
        if not _LOCK.acquire(timeout=_TRANSACTION_WAIT_SECONDS):
            raise KeyboardError(t('Başka bir USB aktarımı sürüyor. Aktarımın bitmesini bekle.'))
        self._local_lock_held=True
        try:
            self._process_mutex=_ProcessMutex()
            self._process_mutex.acquire(max(0, int((deadline-time.monotonic())*1000)))
            if self._process_mutex.abandoned:
                self.log('previous_transaction_abandoned')
            matches=discover()
            for interface in (3,2):
                handle=hid.device();handle.open_path(matches[interface]['path'])
                if bytes(handle.get_report_descriptor())!=DESCRIPTORS[interface]:
                    handle.close(); raise KeyboardError(t('USB tanımı doğrulanan KB884L modeliyle eşleşmiyor.'))
                if interface==3:self.ctrl=handle
                else:self.lcd=handle
            self.log('open',model='KB884L',release=RELEASE)
            return self
        except BaseException:
            try:self.close()
            finally:self._release_locks()
            raise
    def _release_locks(self):
        try:
            if self._process_mutex:
                self._process_mutex.close()
                self._process_mutex=None
        finally:
            if self._local_lock_held:
                self._local_lock_held=False
                _LOCK.release()
    def close(self):
        for name in ('lcd','ctrl'):
            handle=getattr(self,name,None)
            if handle:
                try:handle.close()
                except OSError:pass
                setattr(self,name,None)
    def __exit__(self,*args):
        try:self.close()
        finally:self._release_locks()
    def packet(self,payload,echo=True):
        if len(payload)!=64:raise ValueError('Control packet must contain exactly 64 bytes')
        time.sleep(.015)
        written=self.ctrl.send_feature_report(b'\x00'+payload)
        if written!=65:raise KeyboardError(t('USB komutu eksik gönderildi ({written}/65).', written=written))
        time.sleep(.015)
        reply=bytes(self.ctrl.get_feature_report(0,65))
        if len(reply)==65 and reply[0]==0:reply=reply[1:]
        self.log('feature',command=payload[:10].hex(),reply=reply[:12].hex())
        if len(reply)!=64:raise KeyboardError(t('Klavye komut yanıtı eksik.'))
        if not echo:
            # Raw clock data is echoed unchanged, including its year byte;
            # unlike command replies it does not contain a status field.
            if reply!=payload:raise KeyboardError(t('Klavye saat/sayfa verisini doğrulamadı.'))
            return reply
        if echo and reply[:2]!=payload[:2]:raise KeyboardError(t('Klavye başka bir komutun yanıtını verdi. HAVIT’i tamamen kapat.'))
        # The vendor implementation repeats a pending (FF) packet once.
        if reply[3]==0xff:
            time.sleep(.06)
            self.ctrl.send_feature_report(b'\x00'+payload)
            time.sleep(.015)
            reply=bytes(self.ctrl.get_feature_report(0,65))
            if len(reply)==65 and reply[0]==0:reply=reply[1:]
            self.log('feature_retry',command=payload[:10].hex(),reply=reply[:12].hex())
            if len(reply)!=64 or (echo and reply[:2]!=payload[:2]):raise KeyboardError(t('Klavye komut yanıtı doğrulanamadı.'))
        if reply[3]!=1:raise KeyboardError(t('Klavye komutu onaylamadı (durum {status}).', status=f'{reply[3]:02x}'))
        return reply
    def command(self,opcode,slot=0,pages=0):
        # These constants come from DeviceDriver.exe 0x423a93..0x423c10.
        if opcode not in (0x18,0x72,0x28,0x02):raise ValueError('Unsupported command')
        packet=bytearray(64);packet[0:3]=bytes((4,opcode,slot));packet[8:10]=struct.pack('<H',pages)
        return self.packet(bytes(packet))
    def select_page(self,slot):
        if slot not in (1,2,3):raise ValueError('Only the three Studio pages may be selected')
        now=datetime.now();data=bytearray(64)
        data[1:9]=bytes((slot,0x5a,now.year%2000,now.month,now.day,now.hour,now.minute,now.second))
        data[62:64]=b'\xaa\x55'
        self.command(0x18);self.command(0x28,pages=1);self.packet(bytes(data),echo=False);self.command(0x02)
        self.log('select',slot=slot)
    def upload(self,frames,durations,slot=1,progress=None,select=False):
        if slot not in (1,2,3):raise ValueError('Only the three Studio pages may be written')
        data=build_buffer(frames,durations); pages=len(data)//PAGE_SIZE
        self.log('begin_upload',slot=slot,frames=len(frames),pages=pages,sha256=hashlib.sha256(data).hexdigest())
        self.command(0x18);self.command(0x72,slot=slot,pages=pages)
        progress_callback=progress
        for index in range(pages):
            page=data[index*PAGE_SIZE:(index+1)*PAGE_SIZE]
            written=self.lcd.write(b'\x00'+page)
            if written!=PAGE_SIZE+1:raise KeyboardError(t('USB veri paketi eksik ({written}/4097).', written=written))
            acknowledgement=bytes(self.lcd.read(64,3000))
            if len(acknowledgement)!=64:raise KeyboardError(t('Klavye {page}. veri paketini onaylamadı. Aktarım durduruldu.', page=index+1))
            self.log('page',index=index+1,total=pages,ack=acknowledgement[:12].hex())
            if progress_callback:
                try:
                    progress_callback(round((index+1)*100/pages))
                except Exception as error:
                    # A disappearing UI is not a reason to abandon a device write.
                    # Disable this observer after its first failure, then finish
                    # the acknowledged pages and commit the transaction normally.
                    progress_callback=None
                    try:self.log('progress_callback_failed',error_type=type(error).__name__)
                    except Exception:pass
        self.command(0x02)
        self.log('uploaded',slot=slot,frames=len(frames),pages=pages)
        if select:self.select_page(slot)
        return {'slot':slot,'frames':len(frames),'pages':pages}
