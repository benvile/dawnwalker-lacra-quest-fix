param(
    [string]$Version = '0.1.0'
)

$ErrorActionPreference = 'Stop'

$root = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $root

$release = Join-Path $root 'dist\Dawnwalker-Lacra-Fix'
$executable = Join-Path $release 'Dawnwalker-Lacra-Fix.exe'
if (-not (Test-Path -LiteralPath $executable)) {
    throw 'Build the Windows application before preparing release artifacts.'
}

$sourceCache = Join-Path $root '.private\release-sources'
New-Item -ItemType Directory -Force -Path $sourceCache | Out-Null

$sources = @(
    @{
        Name = 'pyooz-0.0.8.tar.gz'
        Url = 'https://files.pythonhosted.org/packages/97/95/025dc21dbfe92855d6ab7b3c960159a682f647f71ac748714f0512695af6/pyooz-0.0.8.tar.gz'
        Sha256 = '98916331773493764483bc6448c9c6166bf2440939abe77cd140509038cc3adf'
    },
    @{
        Name = 'pyside-setup-everywhere-src-6.11.2.zip'
        Url = 'https://download.qt.io/official_releases/QtForPython/pyside6/PySide6-6.11.2-src/pyside-setup-everywhere-src-6.11.2.zip'
        Sha256 = 'c0fdd62b91a1d36d5ee2e1fb71050a32fbc93fcdeef0fdcb41d29afaaf00d9b5'
    },
    @{
        Name = 'qtbase-everywhere-src-6.11.2.tar.xz'
        Url = 'https://download.qt.io/official_releases/qt/6.11/6.11.2/submodules/qtbase-everywhere-src-6.11.2.tar.xz'
        Sha256 = '5b2e00eccaf5a4d8c14134ffa0ea8dfd0a35ae1ffc7f8d87fa4305a1ed23cf22'
    }
)

foreach ($source in $sources) {
    $destination = Join-Path $sourceCache $source.Name
    $valid = $false
    if (Test-Path -LiteralPath $destination) {
        $actual = (Get-FileHash -LiteralPath $destination -Algorithm SHA256).Hash.ToLowerInvariant()
        $valid = $actual -eq $source.Sha256
    }
    if (-not $valid) {
        & curl.exe --fail --location --connect-timeout 20 --max-time 600 `
            --output $destination $source.Url
        if ($LASTEXITCODE -ne 0) {
            throw "Download failed: $($source.Url)"
        }
    }
    $actual = (Get-FileHash -LiteralPath $destination -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($actual -ne $source.Sha256) {
        throw "Checksum mismatch for $($source.Name): $actual"
    }
}

$privateRoot = [System.IO.Path]::GetFullPath((Join-Path $root '.private'))
$work = Join-Path $privateRoot ("release-work-" + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $work | Out-Null

try {
    $qtSource = Join-Path $work 'qtbase'
    $pysideSource = Join-Path $work 'pyside'
    New-Item -ItemType Directory -Path $qtSource,$pysideSource | Out-Null
    & tar.exe -xf (Join-Path $sourceCache 'qtbase-everywhere-src-6.11.2.tar.xz') -C $qtSource
    if ($LASTEXITCODE -ne 0) { throw 'Could not extract Qt Base sources.' }
    & tar.exe -xf (Join-Path $sourceCache 'pyside-setup-everywhere-src-6.11.2.zip') -C $pysideSource
    if ($LASTEXITCODE -ne 0) { throw 'Could not extract PySide sources.' }

    $qtRoot = Get-ChildItem -LiteralPath $qtSource -Directory | Select-Object -First 1
    $pysideRoot = Get-ChildItem -LiteralPath $pysideSource -Directory | Select-Object -First 1
    if (-not $qtRoot -or -not $pysideRoot) {
        throw 'Upstream source archive layout was not recognized.'
    }

    $qtNotices = Join-Path $release 'QT_THIRD_PARTY_NOTICES.txt'
    & .\.venv\Scripts\python.exe scripts\generate_attributions.py `
        $qtRoot.FullName $qtNotices `
        --title 'Qt Base 6.11.2 third-party notices' `
        --module qtcore --module qtgui --module qtwidgets
    if ($LASTEXITCODE -ne 0) { throw 'Qt attribution generation failed.' }

    $pysideNotices = Join-Path $release 'PYSIDE_THIRD_PARTY_NOTICES.txt'
    & .\.venv\Scripts\python.exe scripts\generate_attributions.py `
        $pysideRoot.FullName $pysideNotices `
        --title 'PySide6 and Shiboken6 6.11.2 third-party notices' `
        --include-segment 'sources/'
    if ($LASTEXITCODE -ne 0) { throw 'PySide attribution generation failed.' }

    $qtLicenseTarget = Join-Path $release 'LICENSES\Qt'
    New-Item -ItemType Directory -Force -Path $qtLicenseTarget | Out-Null
    Copy-Item -Path (Join-Path $qtRoot.FullName 'LICENSES\*') `
        -Destination $qtLicenseTarget -Force

    $manifest = @"
# Corresponding source manifest

Release: Dawnwalker Lacra Quest Fix $Version

The application source is the Git tag v${Version}:
https://github.com/sonervous7/dawnwalker-lacra-quest-fix/tree/v$Version

The following unmodified upstream source archives correspond to copyleft
components shipped in the Windows package:

| Component | Archive | SHA-256 | Upstream |
| --- | --- | --- | --- |
| pyooz 0.0.8 | pyooz-0.0.8.tar.gz | 98916331773493764483bc6448c9c6166bf2440939abe77cd140509038cc3adf | PyPI |
| PySide6 and Shiboken6 6.11.2 | pyside-setup-everywhere-src-6.11.2.zip | c0fdd62b91a1d36d5ee2e1fb71050a32fbc93fcdeef0fdcb41d29afaaf00d9b5 | Qt Project |
| Qt Base 6.11.2 | qtbase-everywhere-src-6.11.2.tar.xz | 5b2e00eccaf5a4d8c14134ffa0ea8dfd0a35ae1ffc7f8d87fa4305a1ed23cf22 | Qt Project |

The URLs used to retrieve these archives are pinned in
`scripts/prepare_release.ps1` in the application source.
"@

    $sourceOffer = @"
# Corresponding source

The complete application source for this release and the source-compliance
archive for bundled GPL/LGPL components are available on the same GitHub release
page:

https://github.com/sonervous7/dawnwalker-lacra-quest-fix/releases/tag/v$Version

See `SOURCE_MANIFEST.md` inside
`Dawnwalker-Lacra-Fix-$Version-source-compliance.zip` for exact versions,
upstream locations, and SHA-256 checksums.
"@
    Set-Content -LiteralPath (Join-Path $release 'SOURCE_OFFER.md') `
        -Value $sourceOffer -Encoding utf8NoBOM

    $complianceName = "Dawnwalker-Lacra-Fix-$Version-source-compliance"
    $complianceRoot = Join-Path $work $complianceName
    $thirdParty = Join-Path $complianceRoot 'third_party'
    New-Item -ItemType Directory -Path $thirdParty | Out-Null
    Set-Content -LiteralPath (Join-Path $complianceRoot 'SOURCE_MANIFEST.md') `
        -Value $manifest -Encoding utf8NoBOM
    Copy-Item -LiteralPath (Join-Path $root 'LICENSE') -Destination $complianceRoot
    Copy-Item -LiteralPath (Join-Path $release 'LICENSES') -Destination $complianceRoot -Recurse
    Copy-Item -LiteralPath (Join-Path $release 'SOURCE_OFFER.md') -Destination $complianceRoot
    Copy-Item -LiteralPath (Join-Path $root 'THIRD_PARTY_NOTICES.md') -Destination $complianceRoot
    Copy-Item -LiteralPath $qtNotices,$pysideNotices -Destination $complianceRoot
    foreach ($source in $sources) {
        Copy-Item -LiteralPath (Join-Path $sourceCache $source.Name) -Destination $thirdParty
    }

    $binaryZip = Join-Path $root "dist\Dawnwalker-Lacra-Fix-$Version-windows-x64.zip"
    $sourceZip = Join-Path $root "dist\$complianceName.zip"
    Compress-Archive -Path $release -DestinationPath $binaryZip -CompressionLevel Optimal -Force
    Compress-Archive -Path $complianceRoot -DestinationPath $sourceZip -CompressionLevel Optimal -Force

    $hashLines = foreach ($artifact in @($binaryZip, $sourceZip)) {
        $hash = (Get-FileHash -LiteralPath $artifact -Algorithm SHA256).Hash.ToLowerInvariant()
        "$hash  $([System.IO.Path]::GetFileName($artifact))"
    }
    Set-Content -LiteralPath (Join-Path $root 'dist\SHA256SUMS.txt') `
        -Value $hashLines -Encoding ascii
    Write-Output $binaryZip
    Write-Output $sourceZip
} finally {
    $resolvedWork = [System.IO.Path]::GetFullPath($work)
    if ($resolvedWork.StartsWith("$privateRoot\", [System.StringComparison]::OrdinalIgnoreCase) -and
        (Test-Path -LiteralPath $resolvedWork)) {
        Remove-Item -LiteralPath $resolvedWork -Recurse -Force
    }
}
