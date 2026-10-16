# =========================================================================
# start_workers.ps1
# GeMBridge Multi-Worker Distributed Process Launcher for Windows
# Launches 3 dedicated queue workers across Ryzen CPU cores (Solo Mode)
# =========================================================================
param (
    [switch]$Stop,
    [switch]$WithBeat,
    [switch]$WithFlower,
    [switch]$Background
)

$ProjectRoot = $PSScriptRoot
$VenvPython = Join-Path $ProjectRoot "venv\Scripts\python.exe"
$VenvCelery = Join-Path $ProjectRoot "venv\Scripts\celery.exe"

# If -Stop is requested, kill all active celery worker processes
if ($Stop) {
    Write-Host "[*] Stopping all running Celery worker and beat processes..." -ForegroundColor Yellow
    Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object {
        $_.CommandLine -match "tasks\.celery_app" -or ($_.CommandLine -match "celery" -and $_.Name -eq "python.exe")
    } | ForEach-Object {
        Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
    }
    Write-Host "[OK] All GeMBridge Celery workers stopped." -ForegroundColor Green
    exit 0
}

Write-Host "=======================================================================" -ForegroundColor Cyan
Write-Host " GeMBridge Multi-Worker Pipeline Launcher - Local Development" -ForegroundColor Cyan
Write-Host " Platform: Windows - AMD Ryzen 5 4600H (6 Cores / 12 Threads)" -ForegroundColor Cyan
Write-Host " Mode: Queue Isolation (3 Dedicated Independent OS Processes)" -ForegroundColor Cyan
Write-Host "=======================================================================" -ForegroundColor Cyan

# 1. Verify Redis
Write-Host "[1/3] Checking Redis Broker on localhost:6379..." -NoNewline
try {
    $redisPing = & docker exec redis-server-gem redis-cli ping 2>$null
    if ($redisPing -match "PONG") {
        Write-Host " [ONLINE (Docker: redis-server-gem)]" -ForegroundColor Green
    } else {
        throw "Redis container not responding with PONG"
    }
} catch {
    Write-Host " [OFFLINE]" -ForegroundColor Red
    Write-Host "[-] Please ensure the 'redis-server-gem' container is running: docker start redis-server-gem" -ForegroundColor Red
    exit 1
}

# 2. Verify PostgreSQL gem-bridge
Write-Host "[2/4] Checking PostgreSQL on localhost:5432 (gem-bridge)..." -NoNewline
try {
    $pgCode = "import psycopg2; c = psycopg2.connect('postgresql://postgres:postgres@localhost:5432/gem-bridge'); c.close(); print('OK')"
    $pgCheck = & $VenvPython -c $pgCode 2>$null
    if ($pgCheck -match "OK") {
        Write-Host " [ONLINE]" -ForegroundColor Green
    } else {
        throw "Could not connect to gem-bridge database"
    }
} catch {
    Write-Host " [OFFLINE]" -ForegroundColor Red
    Write-Host "[-] Please ensure local PostgreSQL is running and database 'gem-bridge' exists." -ForegroundColor Red
    exit 1
}

# 3. Verify MinIO S3 Object Storage
Write-Host "[3/4] Checking MinIO S3 on localhost:9000 (gem-tenders)..." -NoNewline
try {
    $minioCode = "from utils.s3_storage import ensure_bucket_exists; ensure_bucket_exists('gem-tenders'); print('OK')"
    $minioCheck = & $VenvPython -c $minioCode 2>$null
    if ($minioCheck -match "OK") {
        Write-Host " [ONLINE (Docker: minio-server-gem)]" -ForegroundColor Green
    } else {
        throw "Could not connect to MinIO object storage"
    }
} catch {
    Write-Host " [OFFLINE]" -ForegroundColor Red
    Write-Host "[-] Please ensure the 'minio-server-gem' container is running: docker start minio-server-gem" -ForegroundColor Red
    exit 1
}

# 4. Launch the 3 Worker Queues
Write-Host "[4/4] Launching 3 Dedicated Celery Workers in separate terminals..." -ForegroundColor Cyan


$WorkerCommands = @(
    @{
        Name = 'Tier 1: Scraper Worker [scraping_queue]'
        Queue = 'scraping_queue'
        WorkerName = 'worker_scraper@local'
        Color = 'Yellow'
    },
    @{
        Name = 'Tier 2: Document and OCR Worker [document_queue]'
        Queue = 'document_queue'
        WorkerName = 'worker_document@local'
        Color = 'Cyan'
    },
    @{
        Name = 'Tier 3: ATC and RAG Worker [atc_rag_queue]'
        Queue = 'atc_rag_queue'
        WorkerName = 'worker_atc@local'
        Color = 'Magenta'
    }
)

foreach ($w in $WorkerCommands) {
    Write-Host "  -> Starting $($w.Name)..." -ForegroundColor $w.Color
    $cmd = "cd '$ProjectRoot'; & '$VenvCelery' -A tasks.celery_app worker -Q $($w.Queue) -n $($w.WorkerName) -P solo --loglevel=INFO"
    
    if ($Background) {
        Start-Process powershell.exe -ArgumentList "-NoExit", "-Command", $cmd -WindowStyle Hidden
    } else {
        Start-Process powershell.exe -ArgumentList "-NoExit", "-Command", $cmd
    }
    Start-Sleep -Milliseconds 600
}

# Optional Celery Beat
if ($WithBeat) {
    Write-Host "  -> Starting Celery Beat Periodic Scheduler..." -ForegroundColor Green
    $beatCmd = "cd '$ProjectRoot'; & '$VenvCelery' -A tasks.celery_app beat -s 'logs/celerybeat-schedule' --loglevel=INFO"
    Start-Process powershell.exe -ArgumentList "-NoExit", "-Command", $beatCmd
}

# Optional Flower Web Monitoring Dashboard
if ($WithFlower) {
    Write-Host "  -> Starting Flower Real-Time Web Dashboard on http://localhost:5555..." -ForegroundColor Green
    $flowerCmd = "cd '$ProjectRoot'; & '$VenvCelery' -A tasks.celery_app flower --port=5555"
    Start-Process powershell.exe -ArgumentList "-NoExit", "-Command", $flowerCmd
}

Write-Host "`n[OK] All requested services dispatched successfully!" -ForegroundColor Green
Write-Host "To stop all workers anytime, run: .\start_workers.ps1 -Stop`n" -ForegroundColor Yellow
