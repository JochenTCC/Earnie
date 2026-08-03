#Requires -Version 5.1
<#
.SYNOPSIS
  Swap Earnie HTTP host in a Loxone Config project (NAS <-> Dev-PC).

.DESCRIPTION
  Replaces Virtual In/Out base URLs:
    http://DS-KO-DO-2:8541  <->  http://dev-pc:8541
    http://DS-KO-DO-2:8501  <->  http://dev-pc:8501

  -Target pc  -> NAS hostname becomes Dev-PC
  -Target nas -> Dev-PC hostname becomes NAS

  Supports plain XML/text and .Loxone ZIP projects (rewrites matching
  entries inside the archive). Creates a .bak next to the file first.

.PARAMETER Target
  pc | nas

.PARAMETER Path
  Path to .Loxone project or plain XML/text file containing the URLs.

.EXAMPLE
  .\scripts\swap_loxone_earnie_host.ps1 -Target pc -Path "D:\Loxone\Haus.Loxone"

.EXAMPLE
  .\scripts\swap_loxone_earnie_host.ps1 nas "D:\Loxone\Haus.Loxone"
#>
param(
    [Parameter(Mandatory = $true, Position = 0)]
    [ValidateSet("pc", "nas")]
    [string]$Target,

    [Parameter(Mandatory = $true, Position = 1)]
    [string]$Path
)

$ErrorActionPreference = "Stop"

$NasHost = "DS-KO-DO-2"
$PcHost = "dev-pc"
$Ports = @(8541, 8501)

function Get-ReplacementPairs {
    param([string]$Direction)
    $pairs = @()
    foreach ($port in $Ports) {
        $nasUrl = "http://${NasHost}:${port}"
        $pcUrl = "http://${PcHost}:${port}"
        if ($Direction -eq "pc") {
            $pairs += [pscustomobject]@{ From = $nasUrl; To = $pcUrl }
        }
        else {
            $pairs += [pscustomobject]@{ From = $pcUrl; To = $nasUrl }
        }
    }
    return $pairs
}

function Invoke-HostSwap {
    param(
        [string]$Text,
        [object[]]$Pairs
    )
    $total = 0
    $updated = $Text
    foreach ($pair in $Pairs) {
        # Case-insensitive host match; keep original path/query after host:port
        $pattern = [regex]::Escape($pair.From)
        $regex = [regex]::new($pattern, [System.Text.RegularExpressions.RegexOptions]::IgnoreCase)
        $m = $regex.Matches($updated)
        if ($m.Count -gt 0) {
            $total += $m.Count
            $updated = $regex.Replace($updated, $pair.To)
        }
    }
    return @{ Text = $updated; Count = $total }
}

function Test-IsZipFile {
    param([string]$FilePath)
    $fs = [System.IO.File]::OpenRead($FilePath)
    try {
        $b0 = $fs.ReadByte()
        $b1 = $fs.ReadByte()
        # ZIP local header PK\x03\x04
        return ($b0 -eq 0x50 -and $b1 -eq 0x4B)
    }
    finally {
        $fs.Dispose()
    }
}

function Update-PlainFile {
    param(
        [string]$FilePath,
        [object[]]$Pairs
    )
    $encoding = New-Object System.Text.UTF8Encoding $false
    $raw = [System.IO.File]::ReadAllText($FilePath)
    $result = Invoke-HostSwap -Text $raw -Pairs $Pairs
    if ($result.Count -eq 0) {
        return 0
    }
    [System.IO.File]::WriteAllText($FilePath, $result.Text, $encoding)
    return $result.Count
}

function Update-LoxoneZip {
    param(
        [string]$FilePath,
        [object[]]$Pairs
    )
    Add-Type -AssemblyName System.IO.Compression
    Add-Type -AssemblyName System.IO.Compression.FileSystem

    $total = 0
    $zip = [System.IO.Compression.ZipFile]::Open(
        $FilePath,
        [System.IO.Compression.ZipArchiveMode]::Update
    )
    try {
        $entries = @($zip.Entries)
        foreach ($entry in $entries) {
            if ($entry.Length -le 0) { continue }
            # Skip obvious binaries
            $name = $entry.FullName
            if ($name -match '\.(png|jpg|jpeg|gif|bmp|ico|pdf|exe|dll)$') { continue }

            $reader = New-Object System.IO.StreamReader($entry.Open())
            try {
                $content = $reader.ReadToEnd()
            }
            finally {
                $reader.Dispose()
            }

            $result = Invoke-HostSwap -Text $content -Pairs $Pairs
            if ($result.Count -eq 0) { continue }

            $entry.Delete()
            $newEntry = $zip.CreateEntry($name, [System.IO.Compression.CompressionLevel]::Optimal)
            $writer = New-Object System.IO.StreamWriter($newEntry.Open())
            try {
                $writer.Write($result.Text)
            }
            finally {
                $writer.Dispose()
            }
            $total += $result.Count
            Write-Host ("  updated entry: {0} ({1} replacement(s))" -f $name, $result.Count)
        }
    }
    finally {
        $zip.Dispose()
    }
    return $total
}

# --- main ---
$resolved = Resolve-Path -LiteralPath $Path
$filePath = $resolved.Path
if (-not (Test-Path -LiteralPath $filePath -PathType Leaf)) {
    Write-Error "File not found: $Path"
}

$pairs = Get-ReplacementPairs -Direction $Target
Write-Host ("Target={0}" -f $Target)
foreach ($p in $pairs) {
    Write-Host ("  {0}  ->  {1}" -f $p.From, $p.To)
}

$bak = "$filePath.bak"
Copy-Item -LiteralPath $filePath -Destination $bak -Force
Write-Host ("Backup: {0}" -f $bak)

$count = 0
if (Test-IsZipFile -FilePath $filePath) {
    Write-Host "Format: ZIP (.Loxone or similar)"
    $count = Update-LoxoneZip -FilePath $filePath -Pairs $pairs
}
else {
    Write-Host "Format: plain text/XML"
    $count = Update-PlainFile -FilePath $filePath -Pairs $pairs
}

if ($count -eq 0) {
    Write-Warning "No matching Earnie URLs found. File left unchanged (backup kept)."
    exit 2
}

Write-Host ("Done: {0} replacement(s)." -f $count)
Write-Host "Reload/save the project in Loxone Config and upload to the Miniserver."
exit 0
