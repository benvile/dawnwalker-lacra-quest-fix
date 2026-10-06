$ErrorActionPreference = 'Stop'

$root = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $root

& .\.venv\Scripts\pyinstaller.exe `
    --noconfirm `
    --clean `
    --onedir `
    --windowed `
    --name Dawnwalker-Lacra-Fix `
    --exclude-module PySide6.QtNetwork `
    --icon 'assets\app-icon.ico' `
    --add-data 'assets;assets' `
    --add-binary '.venv\Lib\site-packages\PySide6\msvcp140_codecvt_ids.dll;PySide6' `
    launcher_gui.py

if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller failed with exit code $LASTEXITCODE"
}

# The Codex workspace runtime adds Poppler's ICU 78 directory to PATH. PyInstaller
# mistakes those DLLs for Qt dependencies, but Qt on Windows expects the OS ICU
# forwarding shim. Bundling Poppler's icuuc.dll causes QtCore error 127.
$release = Join-Path $root 'dist\Dawnwalker-Lacra-Fix'
$internal = Join-Path $root 'dist\Dawnwalker-Lacra-Fix\_internal'
foreach ($name in @('icuuc.dll', 'icudt78.dll')) {
    $candidate = Join-Path $internal $name
    if (Test-Path -LiteralPath $candidate) {
        Remove-Item -LiteralPath $candidate -Force
    }
}

# The PyInstaller Qt hook includes optional formats and backends that this
# Windows-only Widgets application does not use. Keep the runtime small and the
# third-party license inventory deterministic.
$releaseRoot = (Resolve-Path -LiteralPath $release).Path.TrimEnd('\')
function Remove-ReleasePath([string]$relativePath) {
    $candidate = Join-Path $release $relativePath
    if (-not (Test-Path -LiteralPath $candidate)) {
        return
    }
    $resolved = (Resolve-Path -LiteralPath $candidate).Path
    if (-not $resolved.StartsWith("$releaseRoot\", [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to remove a path outside the release directory: $resolved"
    }
    Remove-Item -LiteralPath $resolved -Recurse -Force
}

foreach ($relativePath in @(
    '_internal\PySide6\opengl32sw.dll',
    '_internal\PySide6\Qt6Network.dll',
    '_internal\PySide6\Qt6Svg.dll',
    '_internal\PySide6\plugins\generic',
    '_internal\PySide6\plugins\iconengines',
    '_internal\PySide6\plugins\imageformats',
    '_internal\PySide6\plugins\platforms\qdirect2d.dll',
    '_internal\PySide6\plugins\platforms\qminimal.dll',
    '_internal\PySide6\plugins\platforms\qoffscreen.dll',
    '_internal\PySide6\translations'
)) {
    Remove-ReleasePath $relativePath
}

$qtRoot = Join-Path $internal 'PySide6'
$allowedQtFiles = @(
    'MSVCP140.dll',
    'MSVCP140_1.dll',
    'MSVCP140_2.dll',
    'msvcp140_codecvt_ids.dll',
    'pyside6.abi3.dll',
    'Qt6Core.dll',
    'Qt6Gui.dll',
    'Qt6Widgets.dll',
    'QtCore.pyd',
    'QtGui.pyd',
    'QtWidgets.pyd',
    'VCRUNTIME140.dll',
    'VCRUNTIME140_1.dll',
    'plugins/platforms/qwindows.dll',
    'plugins/styles/qmodernwindowsstyle.dll'
)
$actualQtFiles = Get-ChildItem -LiteralPath $qtRoot -Recurse -File | ForEach-Object {
    $_.FullName.Substring($qtRoot.Length + 1).Replace('\', '/')
}
$unexpectedQtFiles = $actualQtFiles | Where-Object { $_ -notin $allowedQtFiles }
$missingQtFiles = $allowedQtFiles | Where-Object { $_ -notin $actualQtFiles }
if ($unexpectedQtFiles) {
    throw "Unexpected Qt runtime files:`n$($unexpectedQtFiles -join "`n")"
}
if ($missingQtFiles) {
    throw "Required Qt runtime files are missing:`n$($missingQtFiles -join "`n")"
}

$decoder = Join-Path $internal 'ooz.pyd'
if (-not (Test-Path -LiteralPath $decoder)) {
    throw 'The packaged pyooz decoder is missing.'
}

foreach ($document in @('README.md', 'LICENSE', 'THIRD_PARTY_NOTICES.md')) {
    Copy-Item -LiteralPath (Join-Path $root $document) -Destination $release -Force
}
Copy-Item -LiteralPath (Join-Path $root 'LICENSES') -Destination $release -Recurse -Force

Write-Output (Join-Path $root 'dist\Dawnwalker-Lacra-Fix\Dawnwalker-Lacra-Fix.exe')
