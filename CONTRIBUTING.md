# Contributing

Please open an issue with the exact keyboard model, USB release descriptor, Windows/Python version, reproduction steps and expected behavior. Redact file paths, account identifiers and media titles from logs.

Translations live in `i18n.py`, `i18n_backend.py` and the screen catalogue in `screen_ui.py`. Use stable internal layout/theme keys; never translate media metadata or USB protocol constants. Test both English and Turkish.

Run `python -m unittest discover -s tests -p "test_*.py"` on Windows. These tests must not access real USB devices, change startup settings, contact a media service or alter the vendor database.

Protocol proposals should cite the exact driver/firmware revision and evidence. A shared VID/PID, echoed packet or related keyboard is not proof of compatibility. Do not add speculative firmware flashing or arbitrary command probing to the normal application.

Pull requests should explain the user-visible change and relevant validation. Keep generated releases, personal preferences, vendor files and hardware dumps out of Git.
