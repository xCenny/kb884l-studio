"""Build the Windows portable release from a clean checkout."""
from pathlib import Path
import hashlib
import json
import shutil
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def run(*args, timeout=None):
    subprocess.run([str(arg) for arg in args], cwd=ROOT, check=True, timeout=timeout)


def main():
    if sys.platform != 'win32':
        raise SystemExit('This release must be built on Windows x64.')
    version = (ROOT/'VERSION').read_text(encoding='utf-8').strip()
    run(sys.executable, '-m', 'unittest', 'discover', '-s', 'tests', '-p', 'test_*.py')
    run(sys.executable, '-m', 'PyInstaller', '--noconfirm', '--onefile', '--windowed',
        '--name', 'KB884L-Studio', '--icon', ROOT/'kb884l_tray.ico',
        '--add-data', str(ROOT/'kb884l_tray.ico')+';.',
        '--distpath', ROOT/'dist', '--workpath', ROOT/'build/pyinstaller',
        '--specpath', ROOT/'build', '--collect-all', 'winrt', ROOT/'studio.py')
    exe = ROOT/'dist/KB884L-Studio.exe'
    check_dir = ROOT/'build/packaged-self-test'
    run(exe, '--self-test', check_dir, timeout=90)
    report = json.loads((check_dir/'result.json').read_text(encoding='utf-8'))
    if len(report.get('layouts_tested', [])) != 5 or len(report.get('device_loop_layouts', {})) != 5:
        raise SystemExit('Packaged rendering self-test failed.')
    archive = ROOT/f'dist/KB884L-Studio-{version}-windows-x64.zip'
    with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as bundle:
        bundle.write(exe, exe.name)
        for name in ('README.md', 'README.tr.md', 'LICENSE', 'THIRD_PARTY_NOTICES.md', 'CHANGELOG.md'):
            bundle.write(ROOT/name, name)
        for folder in ('LICENSES', 'docs'):
            for path in sorted((ROOT/folder).rglob('*')):
                if path.is_file():
                    bundle.write(path, path.relative_to(ROOT).as_posix())
    checksums = []
    for path in (exe, archive):
        checksums.append(f'{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}')
    (ROOT/'dist/SHA256SUMS.txt').write_text('\n'.join(checksums)+'\n', encoding='ascii')
    print(f'Release ready: {archive.name}')


if __name__ == '__main__':
    main()
