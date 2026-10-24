param([string]$Dir, [string]$Filter = '*.hwpx')
[Console]::OutputEncoding = [Text.Encoding]::UTF8
$hwp = New-Object -ComObject HWPFrame.HwpObject
[void]$hwp.RegisterModule('FilePathCheckDLL', 'FilePathCheckerModule')
try { $hwp.XHwpWindows.Item(0).Visible = $false } catch {}
Get-ChildItem $Dir -Filter $Filter | Sort-Object Name | ForEach-Object {
    $ok = $hwp.Open($_.FullName, 'HWPX', 'forceopen:true;versionwarning:false')
    if (-not $ok) { "{0}`tOPEN_FAIL" -f $_.Name; return }
    $pages = $hwp.PageCount
    $pdf = [IO.Path]::ChangeExtension($_.FullName, '.pdf')
    $sp = $hwp.SaveAs($pdf, 'PDF', '')
    "{0}`tOPEN_OK`tpages={1}`tpdf={2}" -f $_.Name, $pages, $sp
    [void]$hwp.Clear(1)
}
$hwp.Quit()
