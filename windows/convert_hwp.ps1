param(
    [Parameter(Mandatory = $true)][string]$Src,   # 변환할 파일 또는 폴더
    [string]$OutDir = '',                          # 결과 폴더(생략 시 원본과 같은 폴더)
    [string]$Filter = '*.hwp',                     # 폴더일 때 대상
    [ValidateSet('HWPX', 'HWP')][string]$To = 'HWPX',
    [switch]$Overwrite                             # 같은 이름 결과가 있으면 덮어쓰기(기본: 건너뜀)
)
# pe-hwpx: 한글 프로그램(COM 자동화)으로 HWP → HWPX (또는 HWPX → HWP) 변환.
# 원본은 열기만 하고 저장하지 않는다. 결과는 새 파일로 만든다.
[Console]::OutputEncoding = [Text.Encoding]::UTF8
$ext = if ($To -eq 'HWPX') { '.hwpx' } else { '.hwp' }
$files = if (Test-Path -LiteralPath $Src -PathType Container) {
    Get-ChildItem -LiteralPath $Src -File | Where-Object { $_.Name -like $Filter } | Sort-Object Name
} else { @(Get-Item -LiteralPath $Src) }
if (-not $files) { "NO_FILE`t$Src"; exit 1 }
$hwp = New-Object -ComObject HWPFrame.HwpObject
[void]$hwp.RegisterModule('FilePathCheckDLL', 'FilePathCheckerModule')
try { $hwp.XHwpWindows.Item(0).Visible = $false } catch {}
foreach ($f in $files) {
    $dir = if ($OutDir) { $OutDir } else { $f.DirectoryName }
    if (-not (Test-Path -LiteralPath $dir)) { New-Item -ItemType Directory -Path $dir -Force | Out-Null }
    $dst = Join-Path $dir ([IO.Path]::GetFileNameWithoutExtension($f.Name) + $ext)
    if ((Test-Path -LiteralPath $dst) -and -not $Overwrite) { "{0}`tSKIP_EXISTS`t{1}" -f $f.Name, $dst; continue }
    $ok = $hwp.Open($f.FullName, '', 'forceopen:true;versionwarning:false')
    if (-not $ok) { "{0}`tOPEN_FAIL" -f $f.Name; continue }
    $pages = $hwp.PageCount
    $sv = $hwp.SaveAs($dst, $To, '')
    "{0}`tCONVERTED`tpages={1}`tsaved={2}`t{3}" -f $f.Name, $pages, $sv, $dst
    [void]$hwp.Clear(1)
}
$hwp.Quit()
