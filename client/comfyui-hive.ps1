# Manages which ComfyUI-Hive rigs Claude Code can make images and videos on from this PC, for the current Windows user.
#
#   comfyui-hive add 192.168.1.189          (the page's port 8189 unless given: 192.168.1.189:8289)
#   comfyui-hive remove 192.168.1.189
#   comfyui-hive list                        (and whether each rig answers now, with its downloaded models)
#   comfyui-hive unregister                  (removes every rig and the MCP server itself)
#
# The rig list lives only in the server's Claude Code registration (its COMFYUI_HIVE_RIGS), which each command rewrites.
# Results are saved in Videos\ComfyUI-Hive unless COMFYUI_HIVE_OUT is set in this user's environment when adding.
# Keep this file ASCII: Windows PowerShell 5.1 reads a script without a BOM in the ANSI code page.

param(
    [Parameter(Position = 0)][ValidateSet('add', 'remove', 'list', 'unregister')][string]$Action = 'list',
    [Parameter(Position = 1, ValueFromRemainingArguments = $true)][string[]]$Rigs
)

# Not Stop: in PowerShell 5.1 a native command's stderr then becomes a terminating error
$ErrorActionPreference = 'Continue'
$name = 'comfyui-hive'
$defaultPort = 8189
$server = Join-Path (Split-Path -Parent $MyInvocation.MyCommand.Path) 'comfyui_hive_mcp.py'

function Fail([string]$message) {
    Write-Host $message -ForegroundColor Red
    exit 1
}

function Find-Claude {
    $command = Get-Command claude -ErrorAction SilentlyContinue
    if ($command) { return $command.Source }
    $local = Join-Path $env:USERPROFILE '.local\bin\claude.exe'
    if (Test-Path $local) { return $local }
    Fail 'Claude Code (claude) was not found on this PC.'
}

# The py launcher first: on many PCs "python" is the Microsoft Store stub, which opens the Store instead of running
function Find-Python {
    foreach ($candidate in @(@('py', '-3'), @('python'))) {
        $command = Get-Command $candidate[0] -ErrorAction SilentlyContinue
        if (-not $command) { continue }
        $arguments = @($candidate | Select-Object -Skip 1)
        $path = & $command.Source @arguments -c 'import sys; print(sys.executable) if sys.version_info >= (3, 8) else None' 2>$null
        if ($path -and (Test-Path $path.Trim())) { return $path.Trim() }
    }
    Fail 'Python 3.8 or newer was not found. Install it from python.org, then run this again.'
}

# 192.168.1.189, 192.168.1.189:8289 or http://192.168.1.189:8289, as http://host:port
function Normalize([string]$rig) {
    $rig = $rig.Trim().TrimEnd('/') -replace '^https?://', ''
    if ($rig -notmatch '^([A-Za-z0-9.-]+)(:(\d{1,5}))?$') { Fail "Not an address or address:port: $rig" }
    $port = if ($Matches[3]) { $Matches[3] } else { $defaultPort }
    return "http://$($Matches[1]):$port"
}

function Get-Registered([string]$claude) {
    $text = & $claude mcp get $name 2>&1 | Out-String
    if ($text -notmatch 'Scope:\s*User') {
        if ($text -match 'Scope:\s*(\w+)') { Fail "A $name server is registered in another scope ($($Matches[1])), which hides this user's one: remove it with: claude mcp remove $name -s $($Matches[1].ToLower())" }
        return $null
    }
    # The results folder and image folders chosen when it was first added, kept through later adds and removes
    if ($text -match 'COMFYUI_HIVE_OUT=([^\r\n]+)') { $script:registeredOut = $Matches[1].Trim() }
    if ($text -match 'COMFYUI_HIVE_ROOTS=([^\r\n]+)') { $script:registeredRoots = $Matches[1].Trim() }
    if ($text -match 'COMFYUI_HIVE_RIGS=(\S*)') { return @($Matches[1] -split ',' | Where-Object { $_ }) }
    return @()
}

$registeredOut = $null
$registeredRoots = $null

function Show-Rigs([string[]]$urls) {
    foreach ($url in $urls) {
        try {
            $state = Invoke-RestMethod -Uri "$url/api/state" -TimeoutSec 4
            $ready = @($state.models | Where-Object { $_.installed } | ForEach-Object { $_.id })
            $models = if ($ready) { "downloaded: $($ready -join ', ')" } else { 'no model downloaded yet (press Download on its page)' }
            Write-Host "  $url  $($state.gpu.name), ComfyUI $($state.state), $models" -ForegroundColor Green
        } catch {
            Write-Host "  $url  not answering now (fine if that rig is on another flight sheet)" -ForegroundColor Yellow
        }
    }
}

function Add-Server([string]$claude, [string]$python, [string[]]$urls, [string]$out, [string]$roots) {
    $output = & $claude mcp add $name --scope user -e "COMFYUI_HIVE_RIGS=$($urls -join ',')" -e "COMFYUI_HIVE_OUT=$out" `
        -e "COMFYUI_HIVE_ROOTS=$roots" -- $python $server 2>&1 | Out-String
    return @{ ok = ($LASTEXITCODE -eq 0); output = $output }
}

# Rewrites the registration with this list; an empty list removes it. Everything that can fail is checked before the
# old registration goes, and if adding the new one fails anyway the old one is put back.
function Save-Rigs([string]$claude, [string[]]$urls, $current) {
    if (-not $urls) {
        if ($null -ne $current) { & $claude mcp remove $name -s user 2>&1 | Out-Null }
        Write-Host "No rigs left: $name is unregistered for $env:USERNAME."
        return
    }
    $python = Find-Python
    $out = if ($registeredOut) { $registeredOut } elseif ($env:COMFYUI_HIVE_OUT) { $env:COMFYUI_HIVE_OUT } else { Join-Path $env:USERPROFILE 'Videos\ComfyUI-Hive' }
    # Where an image to animate may come from, besides the session's folder and the results folder
    $roots = if ($registeredRoots) { $registeredRoots } else {
        @((Join-Path $env:USERPROFILE 'Pictures'), (Join-Path $env:USERPROFILE 'Downloads'),
            (Join-Path $env:USERPROFILE 'Desktop'), (Join-Path $env:LOCALAPPDATA 'Temp\claude')) -join ';'
    }
    if ($null -ne $current) { & $claude mcp remove $name -s user 2>&1 | Out-Null }
    $added = Add-Server $claude $python $urls $out $roots
    if (-not $added.ok) {
        if ($current) { Add-Server $claude $python $current $out $roots | Out-Null }
        Fail "claude mcp add failed, the registration is as it was: $($added.output)"
    }
    Write-Host "Results are saved in $out"
}

$claude = Find-Claude
$current = Get-Registered $claude
# Assigned inside @() so a single rig stays an array: otherwise += would join the next URL onto it as one string
$list = @($current | Where-Object { $_ })

switch ($Action) {
    'list' {
        if ($null -eq $current) { Write-Host "$name is not registered for $env:USERNAME."; exit 0 }
        Write-Host "$name rigs for $env:USERNAME (each request goes to the least busy one that has the model):"
        Show-Rigs $list
    }
    'add' {
        if (-not $Rigs) { Fail 'Usage: comfyui-hive add <address>[:port] ...' }
        foreach ($rig in $Rigs) {
            $url = Normalize $rig
            if ($list -contains $url) { Write-Host "$url is already registered." } else { $list += $url }
        }
        Save-Rigs $claude $list $current
        Write-Host "$name rigs for $env:USERNAME (each request goes to the least busy one that has the model):"
        Show-Rigs $list
        if ($null -eq $current) { Write-Host 'New Claude Code sessions get comfy_status, comfy_generate, comfy_result and comfy_cancel; sessions already open do not.' }
    }
    'remove' {
        if (-not $Rigs) { Fail 'Usage: comfyui-hive remove <address>[:port] ...' }
        if ($null -eq $current) { Write-Host "$name is not registered for $env:USERNAME."; exit 0 }
        foreach ($rig in $Rigs) {
            $url = Normalize $rig
            if ($list -contains $url) { $list = @($list | Where-Object { $_ -ne $url }) } else { Write-Host "$url was not registered." }
        }
        Save-Rigs $claude $list $current
        if ($list) { Write-Host "$name rigs for ${env:USERNAME}:"; Show-Rigs $list }
    }
    'unregister' {
        if ($null -eq $current) { Write-Host "$name was not registered for $env:USERNAME."; exit 0 }
        Save-Rigs $claude @() $current
    }
}
