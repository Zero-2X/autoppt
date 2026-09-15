param(
    [Parameter(Mandatory = $true)]
    [string]$InputPath,

    [Parameter(Mandatory = $true)]
    [string]$OutputJson,

    [string]$LanguageTag = "zh-Hans-CN",

    [switch]$Quiet
)

$ErrorActionPreference = "Stop"
Add-Type -AssemblyName System.Runtime.WindowsRuntime

$null = [Windows.Media.Ocr.OcrEngine, Windows.Foundation, ContentType = WindowsRuntime]
$null = [Windows.Globalization.Language, Windows.Foundation, ContentType = WindowsRuntime]
$null = [Windows.Storage.StorageFile, Windows.Storage, ContentType = WindowsRuntime]
$null = [Windows.Storage.FileAccessMode, Windows.Storage, ContentType = WindowsRuntime]
$null = [Windows.Storage.Streams.IRandomAccessStream, Windows.Storage.Streams, ContentType = WindowsRuntime]
$null = [Windows.Graphics.Imaging.BitmapDecoder, Windows.Graphics.Imaging, ContentType = WindowsRuntime]
$null = [Windows.Graphics.Imaging.SoftwareBitmap, Windows.Graphics.Imaging, ContentType = WindowsRuntime]

$asTask = (
    [System.WindowsRuntimeSystemExtensions].GetMethods() |
        Where-Object {
            $_.Name -eq "AsTask" -and
            $_.IsGenericMethod -and
            $_.GetParameters().Count -eq 1 -and
            $_.GetParameters()[0].ParameterType.Name -eq "IAsyncOperation``1"
        }
)[0]

function Await-Operation {
    param(
        [Parameter(Mandatory = $true)]$Operation,
        [Parameter(Mandatory = $true)][Type]$ResultType
    )

    $method = $asTask.MakeGenericMethod($ResultType)
    $task = $method.Invoke($null, @($Operation))
    $task.Wait()
    return $task.Result
}

function Rect-ToObject {
    param([Parameter(Mandatory = $true)]$Rect)

    return [ordered]@{
        x = [math]::Round([double]$Rect.X, 3)
        y = [math]::Round([double]$Rect.Y, 3)
        w = [math]::Round([double]$Rect.Width, 3)
        h = [math]::Round([double]$Rect.Height, 3)
    }
}

$resolvedInput = (Resolve-Path -LiteralPath $InputPath).Path
$outputPath = [System.IO.Path]::GetFullPath($OutputJson)
$outputDirectory = [System.IO.Path]::GetDirectoryName($outputPath)
if ($outputDirectory) {
    [System.IO.Directory]::CreateDirectory($outputDirectory) | Out-Null
}

$language = [Windows.Globalization.Language]::new($LanguageTag)
$engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromLanguage($language)
if (-not $engine) {
    $available = [Windows.Media.Ocr.OcrEngine]::AvailableRecognizerLanguages.LanguageTag -join ", "
    throw "Windows OCR language '$LanguageTag' is unavailable. Available: $available"
}

$file = Await-Operation ([Windows.Storage.StorageFile]::GetFileFromPathAsync($resolvedInput)) ([Windows.Storage.StorageFile])
$stream = Await-Operation ($file.OpenAsync([Windows.Storage.FileAccessMode]::Read)) ([Windows.Storage.Streams.IRandomAccessStream])
$decoder = Await-Operation ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream)) ([Windows.Graphics.Imaging.BitmapDecoder])
$bitmap = Await-Operation ($decoder.GetSoftwareBitmapAsync()) ([Windows.Graphics.Imaging.SoftwareBitmap])
$result = Await-Operation ($engine.RecognizeAsync($bitmap)) ([Windows.Media.Ocr.OcrResult])

$lines = @()
$lineIndex = 0
foreach ($line in $result.Lines) {
    $words = @()
    $minX = [double]::PositiveInfinity
    $minY = [double]::PositiveInfinity
    $maxX = [double]::NegativeInfinity
    $maxY = [double]::NegativeInfinity
    foreach ($word in $line.Words) {
        $rect = $word.BoundingRect
        $minX = [math]::Min($minX, [double]$rect.X)
        $minY = [math]::Min($minY, [double]$rect.Y)
        $maxX = [math]::Max($maxX, [double]$rect.X + [double]$rect.Width)
        $maxY = [math]::Max($maxY, [double]$rect.Y + [double]$rect.Height)
        $words += [ordered]@{
            text = $word.Text
            bbox = Rect-ToObject $rect
        }
    }
    if ($words.Count -eq 0) {
        continue
    }
    $lines += [ordered]@{
        id = "line-{0:D3}" -f $lineIndex
        text = $line.Text
        bbox = [ordered]@{
            x = [math]::Round($minX, 3)
            y = [math]::Round($minY, 3)
            w = [math]::Round($maxX - $minX, 3)
            h = [math]::Round($maxY - $minY, 3)
        }
        words = $words
    }
    $lineIndex += 1
}

$payload = [ordered]@{
    source = $resolvedInput
    language = $LanguageTag
    width = [int]$bitmap.PixelWidth
    height = [int]$bitmap.PixelHeight
    text_angle = if ($null -eq $result.TextAngle) { $null } else { [double]$result.TextAngle }
    full_text = $result.Text
    line_count = $lines.Count
    lines = $lines
}

$json = $payload | ConvertTo-Json -Depth 8
[System.IO.File]::WriteAllText($outputPath, $json + [Environment]::NewLine, [System.Text.UTF8Encoding]::new($false))
if (-not $Quiet) {
    Write-Output $json
}

$bitmap.Dispose()
$stream.Dispose()
