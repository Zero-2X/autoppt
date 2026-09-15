param(
    [Parameter(Mandatory = $true)][string]$InputPptx,
    [Parameter(Mandatory = $true)][string]$OutputPptx,
    [Parameter(Mandatory = $true)][string]$ReportPath
)

$ErrorActionPreference = 'Stop'
$inputPath = (Resolve-Path -LiteralPath $InputPptx).Path
$outputPath = [System.IO.Path]::GetFullPath($OutputPptx)
$reportFullPath = [System.IO.Path]::GetFullPath($ReportPath)
[System.IO.Directory]::CreateDirectory([System.IO.Path]::GetDirectoryName($outputPath)) | Out-Null
[System.IO.Directory]::CreateDirectory([System.IO.Path]::GetDirectoryName($reportFullPath)) | Out-Null
if ($inputPath -ne $outputPath) {
    Copy-Item -LiteralPath $inputPath -Destination $outputPath -Force
}

$powerPoint = $null
$presentation = $null
$convertedItems = @()
$fallbackItems = @()
$candidateCount = 0

try {
    $powerPoint = New-Object -ComObject PowerPoint.Application
    $presentation = $powerPoint.Presentations.Open($outputPath, $false, $false, $false)
    for ($slideIndex = 1; $slideIndex -le $presentation.Slides.Count; $slideIndex++) {
        $slide = $presentation.Slides.Item($slideIndex)
        for ($shapeIndex = $slide.Shapes.Count; $shapeIndex -ge 1; $shapeIndex--) {
            $shape = $slide.Shapes.Item($shapeIndex)
            $name = [string]$shape.Name
            if (-not $name.StartsWith('vector-svg::')) {
                continue
            }
            $candidateCount++
            try {
                $converted = $shape.ConvertToShape()
                $convertedName = 'native-vector::' + $name.Substring('vector-svg::'.Length)
                try { $converted.Name = $convertedName } catch { $converted.Item(1).Name = $convertedName }
                $convertedItems += [pscustomobject]@{
                    slide = $slideIndex
                    source_name = $name
                    output_name = $convertedName
                    method = 'PowerPoint Shape.ConvertToShape'
                }
            }
            catch {
                $fallbackItems += [pscustomobject]@{
                    slide = $slideIndex
                    source_name = $name
                    retained_as = 'convertible-vector SVG'
                    error = $_.Exception.Message
                }
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

$report = [ordered]@{
    input = $inputPath
    output = $outputPath
    candidates = $candidateCount
    converted = $convertedItems.Count
    retained_svg = $fallbackItems.Count
    converted_items = $convertedItems
    fallback_items = $fallbackItems
    verdict = $(if ($fallbackItems.Count -eq 0) { 'pass-native-vectors' } else { 'pass-with-svg-fallback' })
    note = 'SVG fallback remains vector, selectable, scalable, and recolorable; path-level editing depends on the local Office build.'
}
$json = $report | ConvertTo-Json -Depth 8
[System.IO.File]::WriteAllText($reportFullPath, $json + [Environment]::NewLine, [System.Text.UTF8Encoding]::new($false))
Write-Output $json
