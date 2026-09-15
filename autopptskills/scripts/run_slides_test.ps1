param(
    [Parameter(Mandatory = $true)][string]$InputPptx,
    [string]$OutputLog = '',
    [string]$TempDirectory = '',
    [string]$PresentationToolsRoot = '',
    [int]$Width = 1600,
    [int]$Height = 900,
    [int]$PadPx = 100
)

$ErrorActionPreference = 'Stop'
$inputPath = (Resolve-Path -LiteralPath $InputPptx).Path

function Find-DependencyRoot {
    $candidates = @(
        $env:CODEX_RUNTIME_DEPENDENCIES,
        $env:CODEX_WORKSPACE_DEPENDENCIES,
        $env:CODEX_DEPENDENCIES,
        (Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies')
    ) | Where-Object { $_ }

    foreach ($candidate in $candidates) {
        $resolved = [System.IO.Path]::GetFullPath($candidate)
        $artifactPackage = Join-Path $resolved 'node\node_modules\@oai\artifact-tool\package.json'
        $python = Join-Path $resolved 'python\python.exe'
        if ((Test-Path -LiteralPath $artifactPackage) -and (Test-Path -LiteralPath $python)) {
            return $resolved
        }
    }
    throw 'Unable to locate the bundled Codex runtime dependencies with Python and @oai/artifact-tool.'
}

function Find-SlidesTest {
    param([string]$ExplicitRoot)

    if ($ExplicitRoot) {
        $explicitPath = if ([System.IO.Path]::GetExtension($ExplicitRoot)) {
            $ExplicitRoot
        }
        else {
            Join-Path $ExplicitRoot 'slides_test.py'
        }
        return (Resolve-Path -LiteralPath $explicitPath).Path
    }

    $presentationsRoot = Join-Path $env:USERPROFILE '.codex\plugins\cache\openai-primary-runtime\presentations'
    $candidate = Get-ChildItem -LiteralPath $presentationsRoot -Directory -ErrorAction SilentlyContinue |
        Sort-Object LastWriteTime -Descending |
        ForEach-Object {
            Join-Path $_.FullName 'skills\presentations\container_tools\slides_test.py'
        } |
        Where-Object { Test-Path -LiteralPath $_ } |
        Select-Object -First 1
    if (-not $candidate) {
        throw "Unable to locate the official presentations container_tools/slides_test.py under $presentationsRoot."
    }
    return [System.IO.Path]::GetFullPath($candidate)
}

$dependencyRoot = Find-DependencyRoot
$slidesTest = Find-SlidesTest -ExplicitRoot $PresentationToolsRoot
$python = Join-Path $dependencyRoot 'python\python.exe'
$runtimeNode = Join-Path $dependencyRoot 'node\bin\node.exe'
$runtimeNodeModules = Join-Path $dependencyRoot 'node\node_modules'
$runtimeBinDir = Join-Path $dependencyRoot 'bin\override'
$runtimeHome = $env:USERPROFILE
$runtimeArtifact = Join-Path $runtimeNodeModules '@oai\artifact-tool\package.json'
if (-not (Test-Path -LiteralPath $runtimeArtifact)) {
    throw "The bundled @oai/artifact-tool package was not found at $runtimeArtifact."
}
if (-not (Test-Path -LiteralPath $runtimeNode -PathType Leaf)) {
    throw "The bundled Node.js executable was not found at $runtimeNode."
}
if (-not (Test-Path -LiteralPath $runtimeNodeModules -PathType Container)) {
    throw "The bundled Node.js package directory was not found at $runtimeNodeModules."
}
if (-not (Test-Path -LiteralPath $runtimeBinDir -PathType Container)) {
    throw "The bundled runtime binary directory was not found at $runtimeBinDir."
}

if (-not $TempDirectory) {
    $TempDirectory = Join-Path (Split-Path -Parent $inputPath) '.slides-test-tmp'
}
$tempRoot = [System.IO.Path]::GetFullPath($TempDirectory)
[System.IO.Directory]::CreateDirectory($tempRoot) | Out-Null
$sessionTemp = Join-Path $tempRoot ([guid]::NewGuid().ToString('N'))
[System.IO.Directory]::CreateDirectory($sessionTemp) | Out-Null

$oldHome = $env:HOME
$oldRuntime = $env:CODEX_RUNTIME_DEPENDENCIES
$oldRuntimeNode = $env:RUNTIME_NODE
$oldRuntimeNodeModules = $env:RUNTIME_NODE_MODULES
$oldRuntimeBinDir = $env:RUNTIME_BIN_DIR
$oldTemp = $env:TEMP
$oldTmp = $env:TMP
$passed = $false
$text = ''

try {
    $env:HOME = $runtimeHome
    $env:CODEX_RUNTIME_DEPENDENCIES = $dependencyRoot
    $env:RUNTIME_NODE = $runtimeNode
    $env:RUNTIME_NODE_MODULES = $runtimeNodeModules
    $env:RUNTIME_BIN_DIR = $runtimeBinDir
    $env:TEMP = $sessionTemp
    $env:TMP = $sessionTemp

    $output = & $python $slidesTest $inputPath --width $Width --height $Height --pad_px $PadPx 2>&1 |
        ForEach-Object { $_.ToString() }
    $exitCode = $LASTEXITCODE
    $text = (($output -join [Environment]::NewLine) + [Environment]::NewLine)
    $output | Write-Output

    if ($OutputLog) {
        $logPath = [System.IO.Path]::GetFullPath($OutputLog)
        [System.IO.Directory]::CreateDirectory([System.IO.Path]::GetDirectoryName($logPath)) | Out-Null
        [System.IO.File]::WriteAllText($logPath, $text, [System.Text.UTF8Encoding]::new($false))
    }

    $passed = ($exitCode -eq 0) -and ($text -match 'Test passed\. No overflow detected\.')
}
finally {
    $env:HOME = $oldHome
    $env:CODEX_RUNTIME_DEPENDENCIES = $oldRuntime
    $env:RUNTIME_NODE = $oldRuntimeNode
    $env:RUNTIME_NODE_MODULES = $oldRuntimeNodeModules
    $env:RUNTIME_BIN_DIR = $oldRuntimeBinDir
    $env:TEMP = $oldTemp
    $env:TMP = $oldTmp
    if ($passed -and (Test-Path -LiteralPath $sessionTemp)) {
        Remove-Item -LiteralPath $sessionTemp -Recurse -Force
    }
}

if (-not $passed) {
    Write-Error "Official slides_test.py did not pass. Diagnostic temporary files are preserved at $sessionTemp."
    exit 1
}

[pscustomobject]@{
    input = $inputPath
    status = 'pass'
    official_slides_test = $slidesTest
    runtime_dependencies = $dependencyRoot
    runtime_node = $runtimeNode
    runtime_node_modules = $runtimeNodeModules
    runtime_bin_dir = $runtimeBinDir
    temporary_files_removed = $true
} | ConvertTo-Json
