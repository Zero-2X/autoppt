param(
    [Parameter(Mandatory = $true)][string]$InputPptx,
    [Parameter(Mandatory = $true)][string]$OutputDirectory,
    [int]$Width = 1600,
    [int]$Height = 900,
    [switch]$RefineNativePanels,
    [double]$CornerAdjustment = 0.09,
    [string]$RefinedPptx = ''
)

$ErrorActionPreference = 'Stop'
$inputPath = (Resolve-Path -LiteralPath $InputPptx).Path
$outputPath = [System.IO.Path]::GetFullPath($OutputDirectory)
[System.IO.Directory]::CreateDirectory($outputPath) | Out-Null
$openPath = $inputPath
if ($RefinedPptx) {
    $openPath = [System.IO.Path]::GetFullPath($RefinedPptx)
    [System.IO.Directory]::CreateDirectory([System.IO.Path]::GetDirectoryName($openPath)) | Out-Null
    if ($inputPath -ne $openPath) {
        Copy-Item -LiteralPath $inputPath -Destination $openPath -Force
    }
}
$powerPoint = $null
$presentation = $null
$refinedCount = 0
$refinedAdjustments = @()

try {
    $powerPoint = New-Object -ComObject PowerPoint.Application
    $presentation = $powerPoint.Presentations.Open($openPath, (-not $RefineNativePanels), $false, $false)
    if ($RefineNativePanels) {
        for ($slideIndex = 1; $slideIndex -le $presentation.Slides.Count; $slideIndex++) {
            $slide = $presentation.Slides.Item($slideIndex)
            for ($shapeIndex = 1; $shapeIndex -le $slide.Shapes.Count; $shapeIndex++) {
                $shape = $slide.Shapes.Item($shapeIndex)
                $name = [string]$shape.Name
                if (-not $name.StartsWith('hf-native-panel-')) {
                    continue
                }
                try {
                    if ($shape.Adjustments.Count -ge 1) {
                        $shapeCornerAdjustment = $CornerAdjustment
                        if ($name -match '__ca_([0-9]+(?:\.[0-9]+)?)$') {
                            $shapeCornerAdjustment = [double]::Parse(
                                $Matches[1],
                                [System.Globalization.CultureInfo]::InvariantCulture
                            )
                        }
                        $shape.Adjustments.Item(1) = $shapeCornerAdjustment
                        $refinedCount++
                        $refinedAdjustments += [pscustomobject]@{
                            slide = $slideIndex
                            name = $name
                            corner_adjustment = $shapeCornerAdjustment
                        }
                    }
                }
                catch { }
            }
        }
        $presentation.Save()
    }
    for ($index = 1; $index -le $presentation.Slides.Count; $index++) {
        $target = Join-Path $outputPath ('slide-{0}.png' -f $index)
        $presentation.Slides.Item($index).Export($target, 'PNG', $Width, $Height)
    }
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

[pscustomobject]@{
    input = $inputPath
    refined_pptx = $openPath
    output_directory = $outputPath
    slides = (Get-ChildItem -LiteralPath $outputPath -Filter 'slide-*.png').Count
    renderer = 'Microsoft PowerPoint'
    refined_native_panels = $refinedCount
    corner_adjustment = $(if ($RefineNativePanels) { $CornerAdjustment } else { $null })
    refined_adjustments = $refinedAdjustments
} | ConvertTo-Json
