"""Behavior tests with fake UI/executors: no windows or USB are opened."""
import sys
from pathlib import Path
from unittest import TestCase,main
from unittest.mock import patch
import threading

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import studio

class Variable:
    def __init__(self,value):self.value=value
    def get(self):return self.value
    def set(self,value):self.value=value
class Widget:
    def configure(self,**kwargs):pass
class Future:
    def __init__(self,error=None):self.ready=False;self.error=error;self.value=None
    def done(self):return self.ready
    def result(self):
        if self.error:raise self.error
        return self.value
class Executor:
    def __init__(self,error=None):self.requests=0;self.error=error;self.stopped=False;self.future=None;self.task=None
    def submit(self,task):
        self.requests+=1;self.task=task;self.future=Future(self.error)
        if self.error:self.future.ready=True
        return self.future
    def execute(self):
        self.future.value=self.task();self.future.ready=True
    def shutdown(self,**kwargs):self.stopped=True
class Keyboard:
    committed=False
    def __enter__(self):return self
    def __exit__(self,*args):pass
    def upload(self,frames,durations,slot,progress,select):
        progress(50);progress(100);type(self).committed=True
        return {'frames':len(frames),'pages':8,'slot':slot}
class Controller:
    maybe_auto_sync=studio.Studio.maybe_auto_sync
    refresh_usb_status=studio.Studio.refresh_usb_status
    _start_usb_upload=studio.Studio._start_usb_upload
    quit_completely=studio.Studio.quit_completely
    def __init__(self,error=None):
        self.auto_sync_var=Variable(True);self.tab='nowbar';self.uploading=False;self.usb_connected=True
        self._closing=False;self._quit_after_upload=False;self._retry_failures=0;self._next_retry_at=0.0
        self.label_var=Variable('CAN');self.note_var=Variable('idle');self.bg_image_path=''
        self.idle_clock_sync_var=Variable(False);self.info={'available':True,'playing':True,'title':'Track','artist':'Artist','cover_hash':'test'}
        self.stats={'cpu':10,'ram':50};self.last_sync_signature=None;self.last_sync_clock=''
        self.last_sync_stats=(10,50);self.last_sync_time=0.0
        self.interval='event';self.mode='animated';self.payload_modes=[];self.pending=[];self.after_threads=[]
        self.upload_btn=Widget();self.usb_label=Widget();self.progress_var=Variable(0);self.status_var=Variable('')
        self.upload_executor=Executor(error);self.media_executor=Executor();self.gif_executor=Executor()
        self.tray=None;self.ipc_sock=None;self.destroyed=False
    def is_media_playing(self):return True
    def effective_layout(self):return 'nowbar_media'
    def effective_mode(self):return self.mode
    def current_theme_key(self):return 'cover'
    def current_sync_interval_key(self):return self.interval
    def build_nowbar_media(self,mode_override=None,clock_override=None):
        self.payload_modes.append(mode_override)
        return {'frames':[None],'durations':[100],'clock':clock_override}
    def after(self,delay,callback):
        self.after_threads.append(threading.get_ident());self.pending.append((delay,callback))
    def poll_transfer(self):
        callback=self.pending.pop(0)[1];callback()
    def persist_settings(self):pass
    def destroy(self):self.destroyed=True

class SchedulingTests(TestCase):
    def setUp(self):
        self.now=100.0
        self.clock=patch.object(studio.time,'monotonic',lambda:self.now);self.clock.start()
    def tearDown(self):self.clock.stop()
    def test_failed_device_uses_increasing_backoff(self):
        app=Controller(OSError('busy'))
        for second in (100,101,102,104):
            self.now=second;app.maybe_auto_sync()
            if app.pending:app.poll_transfer()
        self.assertEqual(app.upload_executor.requests,1)
        self.now=105;app.maybe_auto_sync();app.poll_transfer()
        self.assertEqual(app.upload_executor.requests,2)
        self.assertEqual(app._next_retry_at,115)
        self.now=114;app.maybe_auto_sync()
        self.assertEqual(app.upload_executor.requests,2)
    def test_periodic_refresh_preserves_animation(self):
        app=Controller();app.interval='30s';app._start_usb_upload=lambda *a,**kw:None
        app.maybe_auto_sync();self.now=131;app.maybe_auto_sync()
        self.assertEqual(app.payload_modes,['animated','animated'])
    def test_reconnect_resends_unchanged_event_and_clears_backoff(self):
        app=Controller();app._start_usb_upload=lambda *a,**kw:None
        app.maybe_auto_sync();app.payload_modes.clear();app.usb_connected=False
        app._retry_failures=4;app._next_retry_at=1000
        with patch.object(studio,'check_connection',return_value=(True,'connected')):
            app.refresh_usb_status()
        self.assertEqual(app.payload_modes,['animated'])
        self.assertEqual(app._retry_failures,0)
    def test_quit_waits_for_transaction_and_worker_never_calls_tk(self):
        app=Controller();payload=app.build_nowbar_media()
        app._start_usb_upload(payload,is_auto=True)
        app.quit_completely()
        self.assertFalse(app.destroyed)
        self.assertTrue(app._quit_after_upload)
        Keyboard.committed=False
        with patch.object(studio,'Keyboard',Keyboard):
            worker=threading.Thread(target=app.upload_executor.execute)
            worker.start();worker.join()
        self.assertTrue(Keyboard.committed)
        self.assertEqual(app.after_threads,[threading.get_ident()])
        app.poll_transfer()
        self.assertTrue(app.destroyed)
        self.assertTrue(app.upload_executor.stopped)
    def test_success_resets_retry_state(self):
        app=Controller();app._retry_failures=3;app._next_retry_at=500
        app._start_usb_upload(app.build_nowbar_media(),is_auto=True)
        with patch.object(studio,'Keyboard',Keyboard):app.upload_executor.execute()
        app.poll_transfer()
        self.assertEqual((app._retry_failures,app._next_retry_at),(0,0))

if __name__=='__main__':main()
