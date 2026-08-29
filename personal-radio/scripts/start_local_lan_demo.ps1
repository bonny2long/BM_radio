<#
.SYNOPSIS
Starts BM Radio for this computer and multiple phones on the same trusted Wi-Fi.

.EXAMPLE
powershell -ExecutionPolicy Bypass -File .\scripts\start_local_lan_demo.ps1

.EXAMPLE
powershell -ExecutionPolicy Bypass -File .\scripts\start_local_lan_demo.ps1 -Stop

.EXAMPLE
powershell -ExecutionPolicy Bypass -File .\scripts\start_local_lan_demo.ps1 -Stop -StopDatabase

.NOTES
Run from C:\Dev\NAS\BM_radio\personal-radio. The script never opens PostgreSQL to the LAN,
never creates router port forwarding, and never writes the PostgreSQL password to its state file.
#>

[CmdletBinding()]
param(
    [switch]$Stop,
    [switch]$StopDatabase,
    [ValidateRange(1024, 65535)]
    [int]$FrontendPort = 5173
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$BackendRoot = Join-Path $ProjectRoot "backend"
$FrontendRoot = Join-Path $ProjectRoot "frontend"
$BackendPython = Join-Path $BackendRoot ".venv\Scripts\python.exe"
$ViteCommand = Join-Path $FrontendRoot "node_modules\.bin\vite.cmd"
$ContainerName = "bm-radio-postgres-dev"
$BackendPort = 8094
$RuntimeRoot = Join-Path $env:TEMP "bm-radio-local-lan-demo"
$StatePath = Join-Path $RuntimeRoot "launcher-state.json"
$BackendOutLog = Join-Path $RuntimeRoot "backend.out.log"
$BackendErrLog = Join-Path $RuntimeRoot "backend.err.log"
$FrontendOutLog = Join-Path $RuntimeRoot "frontend.out.log"
$FrontendErrLog = Join-Path $RuntimeRoot "frontend.err.log"

function Get-ListenerProcessId {
    param([Parameter(Mandatory)][int]$Port)

    return Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue |
        Select-Object -ExpandProperty OwningProcess -First 1
}

function Test-PrivateIPv4 {
    param([Parameter(Mandatory)][string]$Address)

    if ($Address -match '^10\.') {
        return $true
    }
    if ($Address -match '^192\.168\.') {
        return $true
    }
    if ($Address -match '^172\.(1[6-9]|2[0-9]|3[01])\.') {
        return $true
    }
    return $false
}

function Get-PrivateLanIPv4 {
    $defaultRoute = Get-NetRoute -DestinationPrefix "0.0.0.0/0" -ErrorAction SilentlyContinue |
        Sort-Object RouteMetric, InterfaceMetric |
        Select-Object -First 1

    if ($defaultRoute) {
        $candidate = Get-NetIPAddress -AddressFamily IPv4 -InterfaceIndex $defaultRoute.InterfaceIndex -ErrorAction SilentlyContinue |
            Where-Object { Test-PrivateIPv4 $_.IPAddress } |
            Select-Object -ExpandProperty IPAddress -First 1
        if ($candidate) {
            return $candidate
        }
    }

    $fallback = Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
        Where-Object { Test-PrivateIPv4 $_.IPAddress } |
        Select-Object -ExpandProperty IPAddress -First 1
    if (-not $fallback) {
        throw "No private Wi-Fi/LAN IPv4 address was found. Connect this computer to the same trusted network as the phones."
    }
    return $fallback
}

function Wait-ForHttp {
    param(
        [Parameter(Mandatory)][string]$Url,
        [int]$TimeoutSeconds = 180
    )

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    do {
        try {
            return Invoke-WebRequest $Url -UseBasicParsing -TimeoutSec 5
        }
        catch {
            Start-Sleep -Seconds 2
        }
    } while ((Get-Date) -lt $deadline)

    throw "Timed out waiting for $Url"
}

function Test-BmRadioApi {
    param([Parameter(Mandatory)][string]$Url)

    try {
        $health = Invoke-RestMethod $Url -TimeoutSec 3
        return $health.app_name -eq "BM Radio" -and $health.status -eq "ok"
    }
    catch {
        return $false
    }
}

function Find-FreeFrontendPort {
    param([Parameter(Mandatory)][int]$StartingPort)

    foreach ($candidate in $StartingPort..([Math]::Min($StartingPort + 20, 65535))) {
        if (-not (Get-ListenerProcessId -Port $candidate)) {
            return $candidate
        }
    }
    throw "No free frontend port was found between $StartingPort and $([Math]::Min($StartingPort + 20, 65535))."
}

function Test-DockerDaemon {
    $previousPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = "SilentlyContinue"
        & docker info 1>$null 2>$null
        return $LASTEXITCODE -eq 0
    }
    finally {
        $ErrorActionPreference = $previousPreference
    }
}

function Stop-LauncherProcess {
    param(
        [Parameter(Mandatory)][pscustomobject]$State,
        [Parameter(Mandatory)][string]$Name
    )

    $startedProperty = "${Name}_started"
    $pidProperty = "${Name}_pid"
    if (-not $State.PSObject.Properties[$startedProperty] -or -not $State.$startedProperty) {
        Write-Host "$Name was not started by this launcher; leaving it alone."
        return
    }

    $recordedPid = [int]$State.$pidProperty
    $process = Get-Process -Id $recordedPid -ErrorAction SilentlyContinue
    if ($process) {
        Stop-Process -Id $recordedPid
        Write-Host "Stopped $Name process $recordedPid."
    }
    else {
        Write-Host "$Name process $recordedPid is already stopped."
    }
}

if ($Stop) {
    if (-not (Test-Path $StatePath -PathType Leaf)) {
        Write-Host "No launcher state exists at $StatePath. No application processes were stopped."
    }
    else {
        $state = Get-Content $StatePath -Raw | ConvertFrom-Json
        Stop-LauncherProcess -State $state -Name "frontend"
        Stop-LauncherProcess -State $state -Name "backend"
        Remove-Item $StatePath -Force
    }

    if ($StopDatabase) {
        $databaseRunning = docker ps --format '{{.Names}}' | Where-Object { $_ -eq $ContainerName }
        if ($databaseRunning) {
            docker stop $ContainerName | Out-Null
            Write-Host "Stopped PostgreSQL container $ContainerName. Database files were not deleted."
        }
        else {
            Write-Host "PostgreSQL container $ContainerName is already stopped."
        }
    }
    else {
        Write-Host "PostgreSQL was left running. Add -StopDatabase if you explicitly want to stop it."
    }
    exit 0
}

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    throw "Docker is not installed or is not on PATH. Start Docker Desktop and try again."
}
if (-not (Get-Command npm.cmd -ErrorAction SilentlyContinue)) {
    throw "Node/npm is not installed or is not on PATH."
}
if (-not (Test-Path $BackendPython -PathType Leaf)) {
    throw "Backend environment is missing: $BackendPython"
}
if (-not (Test-Path $ViteCommand -PathType Leaf)) {
    throw "Frontend dependencies are missing. Run 'npm.cmd ci' once inside $FrontendRoot."
}

New-Item -ItemType Directory -Force $RuntimeRoot | Out-Null

if (-not (Test-DockerDaemon)) {
    $dockerDesktop = Join-Path $env:ProgramFiles "Docker\Docker\Docker Desktop.exe"
    if (-not (Test-Path $dockerDesktop -PathType Leaf)) {
        throw "Docker Desktop is not ready and its launcher was not found at $dockerDesktop."
    }

    Write-Host "Docker Desktop is off. Starting it now; this can take a minute..."
    $desktopProcess = Get-Process -Name "Docker Desktop" -ErrorAction SilentlyContinue
    if (-not $desktopProcess) {
        Start-Process -FilePath $dockerDesktop -WindowStyle Hidden | Out-Null
    }

    $dockerDeadline = (Get-Date).AddMinutes(5)
    do {
        Start-Sleep -Seconds 3
        $dockerReady = Test-DockerDaemon
    } while (-not $dockerReady -and (Get-Date) -lt $dockerDeadline)

    if (-not $dockerReady) {
        throw "Docker Desktop started but its engine was not ready within five minutes. Check Docker Desktop and try again."
    }
}

$containerExists = docker ps -a --format '{{.Names}}' | Where-Object { $_ -eq $ContainerName }
if (-not $containerExists) {
    throw "Required PostgreSQL container '$ContainerName' does not exist. Restore the accepted local PostgreSQL environment first."
}

$databaseStarted = $false
$containerRunning = docker ps --format '{{.Names}}' | Where-Object { $_ -eq $ContainerName }
if (-not $containerRunning) {
    docker start $ContainerName | Out-Null
    $databaseStarted = $true
}

$databaseDeadline = (Get-Date).AddMinutes(3)
do {
    Start-Sleep -Seconds 2
    $databaseHealth = docker inspect $ContainerName --format '{{.State.Health.Status}}'
} while ($databaseHealth -ne "healthy" -and (Get-Date) -lt $databaseDeadline)
if ($databaseHealth -ne "healthy") {
    throw "PostgreSQL did not become healthy. Current state: $databaseHealth"
}

$lanIp = Get-PrivateLanIPv4
$backendStarted = $false
$frontendStarted = $false

$backendPid = Get-ListenerProcessId -Port $BackendPort
if ($backendPid -and -not (Test-BmRadioApi -Url "http://127.0.0.1:${BackendPort}/api/health")) {
    throw "Port $BackendPort is already used by another application (process $backendPid). BM Radio did not stop it."
}
if (-not $backendPid) {
    $containerEnvironment = docker inspect $ContainerName --format '{{range .Config.Env}}{{println .}}{{end}}'
    $passwordLine = $containerEnvironment |
        Where-Object { $_ -like "POSTGRES_PASSWORD=*" } |
        Select-Object -First 1
    if (-not $passwordLine) {
        throw "The protected PostgreSQL password is unavailable from $ContainerName."
    }

    $rawPassword = $passwordLine.Substring("POSTGRES_PASSWORD=".Length)
    $encodedPassword = [uri]::EscapeDataString($rawPassword)
    $env:BM_RADIO_DB_URL = "postgresql+psycopg://bm_radio_app:${encodedPassword}@127.0.0.1:55432/bm_radio"
    $env:APP_ENV = "production"
    $env:BM_RADIO_MUSIC_ROOT = "C:\NAS-Local\nas-data\Music"
    $env:BM_RADIO_AUDIOBOOK_ROOT = "C:\NAS-Local\nas-data\Audiobooks\Library"
    $env:BM_RADIO_BOOK_ROOT = "C:\NAS-Local\nas-data\Books"
    $env:BM_RADIO_CACHE_ROOT = Join-Path $BackendRoot ".runtime_cache"
    $env:BM_RADIO_ARTWORK_CACHE_ROOT = Join-Path $BackendRoot ".runtime_cache\artwork"
    $env:BM_RADIO_API_HOST = "127.0.0.1"
    $env:BM_RADIO_API_PORT = "$BackendPort"
    $env:BM_RADIO_API_DOCS_ENABLED = "false"
    $env:BM_RADIO_CORS_ORIGINS = @(
        "http://127.0.0.1:$FrontendPort",
        "http://localhost:$FrontendPort",
        "http://${lanIp}:$FrontendPort"
    ) | ConvertTo-Json -Compress
    $env:BM_RADIO_ENABLE_LEGACY_DISCOGRAPHY_SCAN = "false"
    $env:PUBLIC_ACCESS = "false"
    $env:ALLOW_FILE_MUTATION = "false"
    $env:ALLOW_DELETE = "false"
    $env:ALLOW_TAG_WRITES = "false"
    $env:SCAN_INGEST_FOLDERS = "false"

    try {
        Start-Process -FilePath $BackendPython `
            -ArgumentList "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "$BackendPort" `
            -WorkingDirectory $BackendRoot `
            -WindowStyle Hidden `
            -RedirectStandardOutput $BackendOutLog `
            -RedirectStandardError $BackendErrLog | Out-Null
        $backendStarted = $true
    }
    finally {
        Remove-Item Env:BM_RADIO_DB_URL -ErrorAction SilentlyContinue
        $rawPassword = $null
        $encodedPassword = $null
        $passwordLine = $null
        $containerEnvironment = $null
    }
}

$requestedFrontendPort = $FrontendPort
$existingFrontendPid = Get-ListenerProcessId -Port $FrontendPort
if ($existingFrontendPid -and -not (Test-BmRadioApi -Url "http://127.0.0.1:${FrontendPort}/api/health")) {
    $FrontendPort = Find-FreeFrontendPort -StartingPort ($FrontendPort + 1)
    Write-Host "Port $requestedFrontendPort belongs to another application. BM Radio will use free port $FrontendPort instead."
}

$frontendPid = Get-ListenerProcessId -Port $FrontendPort
if (-not $frontendPid) {
    $env:VITE_API_BASE_URL = "/api"
    Start-Process -FilePath "npm.cmd" `
        -ArgumentList "run", "dev", "--", "--host", "0.0.0.0", "--port", "$FrontendPort" `
        -WorkingDirectory $FrontendRoot `
        -WindowStyle Hidden `
        -RedirectStandardOutput $FrontendOutLog `
        -RedirectStandardError $FrontendErrLog | Out-Null
    $frontendStarted = $true
}

try {
    $backendResponse = Wait-ForHttp -Url "http://127.0.0.1:${BackendPort}/api/health"
    $computerResponse = Wait-ForHttp -Url "http://127.0.0.1:${FrontendPort}"
    $mobileResponse = Wait-ForHttp -Url "http://${lanIp}:${FrontendPort}"
    $summary = Invoke-RestMethod "http://${lanIp}:${FrontendPort}/api/library/summary" -TimeoutSec 10
}
catch {
    Write-Host "Backend error log: $BackendErrLog"
    Write-Host "Frontend error log: $FrontendErrLog"
    throw
}

$backendPid = Get-ListenerProcessId -Port $BackendPort
$frontendPid = Get-ListenerProcessId -Port $FrontendPort
$state = [ordered]@{
    created_utc = (Get-Date).ToUniversalTime().ToString("o")
    project_root = $ProjectRoot
    lan_ip = $lanIp
    backend_pid = $backendPid
    backend_started = $backendStarted
    frontend_pid = $frontendPid
    frontend_started = $frontendStarted
    frontend_port = $FrontendPort
    backend_port = $BackendPort
    database_started = $databaseStarted
}
$state | ConvertTo-Json | Set-Content $StatePath -Encoding utf8

Write-Host ""
Write-Host "BM Radio is ready." -ForegroundColor Green
Write-Host "Computer: http://127.0.0.1:$FrontendPort"
Write-Host "Phones on the same trusted Wi-Fi: http://${lanIp}:$FrontendPort"
Write-Host "Multiple phones can use that same address at the same time."
Write-Host "Library: $($summary.tracks) tracks, $($summary.artists) artists, $($summary.albums) albums"
Write-Host "PostgreSQL: healthy and loopback-only on 127.0.0.1:55432"
Write-Host ""
Write-Host "If Windows Firewall asks, allow Node.js on Private networks only."
Write-Host "Do not add router port-forwarding or share this address outside your private Wi-Fi."
Write-Host ""
Write-Host "To stop services started by this launcher:"
Write-Host "powershell -ExecutionPolicy Bypass -File `"$PSCommandPath`" -Stop"
Write-Host "To also stop PostgreSQL: add -StopDatabase"
Write-Host "Logs: $RuntimeRoot"
