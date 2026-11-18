import json
from pathlib import Path
import sys,tempfile
from unittest import TestCase,main
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import studio_core

class SettingsEncodingTests(TestCase):
    def test_windows_utf8_bom_preserves_settings(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'settings.json'
            settings={'sync_interval':'30s','note':'Etkinlik yok.','bg_image_path':'wallpaper.gif'}
            path.write_text(json.dumps(settings,ensure_ascii=False),encoding='utf-8-sig')
            with patch.object(studio_core,'settings_path',return_value=path):
                self.assertEqual(studio_core.load_settings(),settings)

if __name__=='__main__':main()
