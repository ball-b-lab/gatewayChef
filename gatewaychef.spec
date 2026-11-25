# -*- mode: python ; coding: utf-8 -*-

import os
from PyInstaller.utils.hooks import collect_submodules

block_cipher = None

project_dir = os.path.abspath(os.getcwd())

hiddenimports = (
    collect_submodules('flask') + collect_submodules('jinja2')
    # Einrichtungsstation im WLAN-Modus laeuft in-process (gateway_setup.main)
    + collect_submodules('services') + collect_submodules('utils') + ['scripts.gateway_setup', 'scripts.gateway_probe']
    + collect_submodules('routes') + collect_submodules('repositories') + collect_submodules('cryptography')
)

app = Analysis(
    ['app.py'],
    pathex=[project_dir],
    binaries=[],
    datas=[
        (os.path.join(project_dir, 'templates'), 'templates'),
        (os.path.join(project_dir, 'static'), 'static'),
        (os.path.join(project_dir, '.env'), '.'),
        (os.path.join(project_dir, 'gateway_profiles'), 'gateway_profiles'),
    ],
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(app.pure, app.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    app.scripts,
    app.binaries,
    app.zipfiles,
    app.datas,
    [],
    name='GatewayChef',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
)
