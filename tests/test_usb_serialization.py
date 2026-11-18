"""No real HID enumeration, handles, reports, or writes are used by these tests."""
from pathlib import Path
import os
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import keyboard_usb as usb
from PIL import Image


def worker(mode, name, ready, release):
    with usb._ProcessMutex(name):
        Path(ready).write_text('ready', encoding='ascii')
        deadline = time.monotonic()+10
        while not Path(release).is_file():
            if time.monotonic()>deadline:
                raise TimeoutError('Parent did not release test worker')
            time.sleep(.01)
        if mode == '--abandon':
            os._exit(0)  # Deliberately leave the named Windows mutex owned.


def wait_file(path, child):
    deadline=time.monotonic()+5
    while not path.is_file():
        if child.poll() is not None:
            raise AssertionError('Mutex worker exited before becoming ready')
        if time.monotonic()>deadline:
            raise TimeoutError('Mutex worker startup timeout')
        time.sleep(.01)


class Control:
    def __init__(self):
        self.closed=False;self.commands=[];self.last=None
    def open_path(self,path):pass
    def get_report_descriptor(self):return usb.DESCRIPTORS[3]
    def send_feature_report(self,data):
        assert len(data)==65 and data[0]==0
        self.last=data[1:];self.commands.append(self.last[1]);return 65
    def get_feature_report(self,report_id,length):
        reply=bytearray(self.last);reply[3]=1
        return b'\x00'+reply
    def close(self):self.closed=True


class Pixels:
    def __init__(self):self.closed=False;self.pages=[]
    def open_path(self,path):pass
    def get_report_descriptor(self):return usb.DESCRIPTORS[2]
    def write(self,data):
        assert len(data)==4097 and data[0]==0
        self.pages.append(data[1:]);return len(data)
    def read(self,length,timeout):return b'\x01\x5a\x02'+b'\x00'*61
    def close(self):self.closed=True


class SerializationTests(unittest.TestCase):
    def test_other_process_times_out_then_acquires_after_release(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);ready=root/'ready';release=root/'release'
            name='Local\\KB884L.ReviewTest.'+uuid.uuid4().hex
            child=subprocess.Popen([sys.executable,__file__,'--hold',name,str(ready),str(release)])
            try:
                wait_file(ready,child)
                mutex=usb._ProcessMutex(name)
                start=time.monotonic()
                with self.assertRaisesRegex(usb.KeyboardError,'Another Studio process|başka bir Studio'):
                    mutex.acquire(120)
                self.assertGreaterEqual(time.monotonic()-start,.09)
                self.assertIsNone(mutex.handle)
                release.touch();self.assertEqual(child.wait(timeout=5),0)
                with usb._ProcessMutex(name) as acquired:
                    self.assertTrue(acquired.owned)
                    self.assertFalse(acquired.abandoned)
            finally:
                release.touch()
                if child.poll() is None:child.wait(timeout=5)

    def test_abandoned_owner_is_recognized_and_released(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);ready=root/'ready';release=root/'release'
            name='Local\\KB884L.ReviewTest.'+uuid.uuid4().hex
            child=subprocess.Popen([sys.executable,__file__,'--abandon',name,str(ready),str(release)])
            mutex=None
            try:
                wait_file(ready,child)
                # Keep a handle to the same kernel object before its owner dies.
                mutex=usb._ProcessMutex(name)
                release.touch();self.assertEqual(child.wait(timeout=5),0)
                mutex.acquire(250)
                self.assertTrue(mutex.owned)
                self.assertTrue(mutex.abandoned)
                mutex.close()
                with usb._ProcessMutex(name) as fresh:
                    self.assertTrue(fresh.owned)
                    self.assertFalse(fresh.abandoned)
            finally:
                if mutex:mutex.close()
                release.touch()
                if child.poll() is None:child.wait(timeout=5)

    def test_open_failure_releases_thread_and_process_locks(self):
        name='Local\\KB884L.ReviewTest.'+uuid.uuid4().hex
        with patch.object(usb,'_PROCESS_MUTEX_NAME',name), \
             patch.object(usb,'discover',side_effect=usb.KeyboardError('mock disconnected')):
            context=usb.Keyboard()
            with self.assertRaisesRegex(usb.KeyboardError,'mock disconnected'):
                context.__enter__()
            self.assertFalse(context._local_lock_held)
            self.assertIsNone(context._process_mutex)
            self.assertTrue(usb._LOCK.acquire(blocking=False))
            usb._LOCK.release()
            with usb._ProcessMutex(name) as acquired:
                self.assertTrue(acquired.owned)

    def test_progress_observer_failure_does_not_interrupt_commit(self):
        control=Control();pixels=Pixels();events=[];calls=[]
        def broken_observer(value):
            calls.append(value)
            raise RuntimeError('mock Tk has closed')
        name='Local\\KB884L.ReviewTest.'+uuid.uuid4().hex
        with patch.object(usb,'_PROCESS_MUTEX_NAME',name), \
             patch.object(usb,'discover',return_value={2:{'path':b'pixels'},3:{'path':b'control'}}), \
             patch.object(usb.hid,'device',side_effect=[control,pixels]), \
             patch.object(usb.time,'sleep',return_value=None):
            with usb.Keyboard(logger=events.append) as keyboard:
                result=keyboard.upload([Image.new('RGB',(160,96),'red')],[100],progress=broken_observer)
        self.assertEqual(result['pages'],8)
        self.assertEqual(len(pixels.pages),8)
        self.assertEqual(control.commands,[0x18,0x72,0x02])
        self.assertEqual(len(calls),1)
        self.assertTrue(control.closed and pixels.closed)
        self.assertEqual(sum(event['event']=='progress_callback_failed' for event in events),1)
        self.assertTrue(any(event['event']=='uploaded' for event in events))
        self.assertTrue(usb._LOCK.acquire(blocking=False))
        usb._LOCK.release()


if __name__=='__main__':
    if len(sys.argv)>1 and sys.argv[1] in ('--hold','--abandon'):
        worker(*sys.argv[1:])
    else:
        unittest.main(verbosity=2)
