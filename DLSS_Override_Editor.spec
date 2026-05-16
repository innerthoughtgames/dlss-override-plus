# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['dlss_override_plus_v2.6.2.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('itg.ico', '.'),
        ('itg.png', '.'),
        ('qr_pix.png', '.'),
        ('rtss_guide_add_star_citizen.png', '.'),
        ('rtss_guide_detours.png', '.'),
        ('COMO_USAR_STANDALONE.html', '.'),
    ],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
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
    name='dlss_override_plus_v2.6.2',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,                # Disabled — UPX compression triggers more AV false positives
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='itg.ico',
    version='version_info.txt',
)
