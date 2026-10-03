# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_submodules
from PyInstaller.utils.hooks import collect_all

datas = [('assets', 'assets'), ('app_icon.ico', '.')]
binaries = []
hiddenimports = ['playwright', 'playwright.async_api', 'playwright._impl', 'playwright._impl._driver', 'curl_cffi', 'curl_cffi.requests', 'webview', 'webview.platforms.edgechromium', 'webview.platforms.winforms']
hiddenimports += collect_submodules('curl_cffi')
tmp_ret = collect_all('playwright')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]


a = Analysis(
    ['olm.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['webview.platforms.android', 'webview.platforms.cocoa', 'webview.platforms.gtk', 'webview.platforms.qt', 'webview.platforms.cef', 'tkinter.test', 'test', 'unittest', 'pydoc_data', 'matplotlib', 'numpy', 'scipy', 'pandas', 'pygame'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='OLMToolPro',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['app_icon.ico'],
)
