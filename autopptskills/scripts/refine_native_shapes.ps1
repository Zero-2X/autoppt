param(
    [Parameter(Mandatory = $true)][string]$InputPptx,
    [Parameter(Mandatory = $true)][string]$OutputPptx,
    [Parameter(Mandatory = $true)][string]$ReportPath,
    [double]$CornerAdjustment = 0.09
)

$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.IO.Compression
Add-Type -AssemblyName System.IO.Compression.FileSystem

function Get-PptxSlideSize {
    param([Parameter(Mandatory = $true)][string]$Path)
    $archive = [System.IO.Compression.ZipFile]::OpenRead($Path)
    try {
        $entry = $archive.GetEntry('ppt/presentation.xml')
        if ($null -eq $entry) {
            throw "ppt/presentation.xml is missing from $Path"
        }
        $stream = $entry.Open()
        try {
            $document = New-Object System.Xml.XmlDocument
            $document.PreserveWhitespace = $true
            $document.Load($stream)
        }
        finally {
            $stream.Dispose()
        }
        $namespaces = New-Object System.Xml.XmlNamespaceManager($document.NameTable)
        $namespaces.AddNamespace('p', 'http://schemas.openxmlformats.org/presentationml/2006/main')
        $node = $document.SelectSingleNode('//p:sldSz', $namespaces)
        if ($null -eq $node) {
            throw "p:sldSz is missing from ppt/presentation.xml in $Path"
        }
        return [pscustomobject]@{
            cx = [int64]$node.GetAttribute('cx')
            cy = [int64]$node.GetAttribute('cy')
        }
    }
    finally {
        $archive.Dispose()
    }
}

function Set-PptxSlideSize {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][int64]$Cx,
        [Parameter(Mandatory = $true)][int64]$Cy
    )
    $archive = [System.IO.Compression.ZipFile]::Open(
        $Path,
        [System.IO.Compression.ZipArchiveMode]::Update
    )
    try {
        $entry = $archive.GetEntry('ppt/presentation.xml')
        if ($null -eq $entry) {
            throw "ppt/presentation.xml is missing from $Path"
        }
        $stream = $entry.Open()
        try {
            $document = New-Object System.Xml.XmlDocument
            $document.PreserveWhitespace = $true
            $document.Load($stream)
        }
        finally {
            $stream.Dispose()
        }
        $namespaces = New-Object System.Xml.XmlNamespaceManager($document.NameTable)
        $namespaces.AddNamespace('p', 'http://schemas.openxmlformats.org/presentationml/2006/main')
        $node = $document.SelectSingleNode('//p:sldSz', $namespaces)
        if ($null -eq $node) {
            throw "p:sldSz is missing from ppt/presentation.xml in $Path"
        }
        $node.SetAttribute('cx', [string]$Cx)
        $node.SetAttribute('cy', [string]$Cy)
        $entry.Delete()
        $replacement = $archive.CreateEntry(
            'ppt/presentation.xml',
            [System.IO.Compression.CompressionLevel]::Optimal
        )
        $replacementStream = $replacement.Open()
        try {
            $settings = New-Object System.Xml.XmlWriterSettings
            $settings.Encoding = [System.Text.UTF8Encoding]::new($false)
            $settings.Indent = $false
            $writer = [System.Xml.XmlWriter]::Create($replacementStream, $settings)
            try {
                $document.Save($writer)
            }
            finally {
                $writer.Dispose()
            }
        }
        finally {
            $replacementStream.Dispose()
        }
    }
    finally {
        $archive.Dispose()
    }
}

$inputPath = (Resolve-Path -LiteralPath $InputPptx).Path
$outputPath = [System.IO.Path]::GetFullPath($OutputPptx)
$reportFullPath = [System.IO.Path]::GetFullPath($ReportPath)
$originalSlideSize = Get-PptxSlideSize -Path $inputPath
[System.IO.Directory]::CreateDirectory([System.IO.Path]::GetDirectoryName($outputPath)) | Out-Null
[System.IO.Directory]::CreateDirectory([System.IO.Path]::GetDirectoryName($reportFullPath)) | Out-Null
if ($inputPath -ne $outputPath) {
    Copy-Item -LiteralPath $inputPath -Destination $outputPath -Force
}

$powerPoint = $null
$presentation = $null
$refined = @()
$skipped = @()
try {
    $powerPoint = New-Object -ComObject PowerPoint.Application
    $presentation = $powerPoint.Presentations.Open($outputPath, $false, $false, $false)
    for ($slideIndex = 1; $slideIndex -le $presentation.Slides.Count; $slideIndex++) {
        $slide = $presentation.Slides.Item($slideIndex)
        for ($shapeIndex = 1; $shapeIndex -le $slide.Shapes.Count; $shapeIndex++) {
            $shape = $slide.Shapes.Item($shapeIndex)
            $name = [string]$shape.Name
            if (-not $name.StartsWith('hf-native-panel-')) {
                continue
            }
            try {
                if ($shape.Adjustments.Count -lt 1) {
                    $skipped += [pscustomobject]@{ slide = $slideIndex; name = $name; reason = 'no-adjustment-handle' }
                    continue
                }
                $shapeCornerAdjustment = $CornerAdjustment
                if ($name -match '__ca_([0-9]+(?:\.[0-9]+)?)$') {
                    $shapeCornerAdjustment = [double]::Parse(
                        $Matches[1],
                        [System.Globalization.CultureInfo]::InvariantCulture
                    )
                }
                $shape.Adjustments.Item(1) = $shapeCornerAdjustment
                $refined += [pscustomobject]@{
                    slide = $slideIndex
                    name = $name
                    corner_adjustment = $shapeCornerAdjustment
                }
            }
            catch {
                $skipped += [pscustomobject]@{ slide = $slideIndex; name = $name; reason = $_.Exception.Message }
            }
        }
    }
    $presentation.Save()
}
finally {
    if ($presentation -ne $null) {
        try { $presentation.Close() } catch { }
        [void][System.Runtime.InteropServices.Marshal]::FinalReleaseComObject($presentation)
    }
    if ($powerPoint -ne $null) {
        try { $powerPoint.Quit() } catch { }
        [void][System.Runtime.InteropServices.Marshal]::FinalReleaseComObject($powerPoint)
    }
    [GC]::Collect()
    [GC]::WaitForPendingFinalizers()
}

$powerPointSlideSize = Get-PptxSlideSize -Path $outputPath
$slideSizeRestored = $false
if (
    $powerPointSlideSize.cx -ne $originalSlideSize.cx -or
    $powerPointSlideSize.cy -ne $originalSlideSize.cy
) {
    Set-PptxSlideSize -Path $outputPath -Cx $originalSlideSize.cx -Cy $originalSlideSize.cy
    $slideSizeRestored = $true
}
$finalSlideSize = Get-PptxSlideSize -Path $outputPath
if (
    $finalSlideSize.cx -ne $originalSlideSize.cx -or
    $finalSlideSize.cy -ne $originalSlideSize.cy
) {
    throw (
        'failed to restore the immutable slide-size contract: ' +
        "expected $($originalSlideSize.cx)x$($originalSlideSize.cy), " +
        "got $($finalSlideSize.cx)x$($finalSlideSize.cy)"
    )
}

$report = [ordered]@{
    input = $inputPath
    output = $outputPath
    corner_adjustment = $CornerAdjustment
    refined = $refined.Count
    skipped = $skipped.Count
    refined_items = $refined
    skipped_items = $skipped
    slide_size_contract = [ordered]@{
        input = $originalSlideSize
        after_powerpoint_save = $powerPointSlideSize
        restored_after_powerpoint_save = $slideSizeRestored
        output = $finalSlideSize
        verdict = 'pass'
    }
    verdict = $(if ($skipped.Count -eq 0) { 'pass' } else { 'pass-with-skips' })
}
$json = $report | ConvertTo-Json -Depth 8
[System.IO.File]::WriteAllText($reportFullPath, $json + [Environment]::NewLine, [System.Text.UTF8Encoding]::new($false))
Write-Output $json
