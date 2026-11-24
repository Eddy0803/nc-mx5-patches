# PyInstaller spec for NC Patcher (build with a 32-bit Python so it can load 32-bit J2534 drivers).
# Use app/build_exe.ps1 rather than calling this directly.
import os
ROOT = os.path.abspath(os.path.join(SPECPATH, '..'))

datas = []
for folder, pattern in (('scripts', '.py'), ('tools', '.py'), ('tests', '.py'), ('ncflash', '.xml')):
    for f in os.listdir(os.path.join(ROOT, folder)):
        if f.endswith(pattern) and f != 'dis.py':
            datas.append((os.path.join(ROOT, folder, f), folder))
datas.append((os.path.join(ROOT, 'patches', 'lfj1ee'), os.path.join('patches', 'lfj1ee')))
datas.append((os.path.join(ROOT, 'LICENSE'), '.'))

# the patch scripts are loaded by path at run time, so PyInstaller can't see what they import
hidden = ['argparse', 'collections', 'contextlib', 'csv', 'datetime', 'importlib.util', 'io', 'json', 're', 'runpy',
          'shutil', 'statistics', 'struct', 'subprocess', 'tempfile', 'time', 'xml.etree.ElementTree', 'winreg', 'ctypes',
          'ctypes.wintypes', 'glob']

a = Analysis([os.path.join(SPECPATH, 'ncpatcher.py')], pathex=[SPECPATH], datas=datas, hiddenimports=hidden,
             excludes=['capstone', 'numpy', 'matplotlib', 'PIL'], noarchive=False)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, a.binaries, a.datas, [], name='NCPatcher', console=False, upx=False,
          version=os.path.join(SPECPATH, 'version_info.txt'))
