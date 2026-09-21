param(
    [Parameter(Mandatory=$true)][string]$InputDocx,
    [Parameter(Mandatory=$true)][string]$OutputPdf
)
$word = New-Object -ComObject Word.Application
$word.Visible = $false
try {
    $doc = $word.Documents.Open($InputDocx, $false, $true)
    # 17 = wdExportFormatPDF; use the Word renderer as an environment fallback.
    $doc.ExportAsFixedFormat($OutputPdf, 17, $false, 0, 0, 1, 1, 0, $true, $true, 1, $true, $true, $false)
    $doc.Close([ref]$false)
} finally {
    $word.Quit()
}
