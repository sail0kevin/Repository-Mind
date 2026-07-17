param(
    [Parameter(Mandatory = $true)] [string] $ExePath,
    [int] $TimeoutSeconds = 45
)

$ErrorActionPreference = "Stop"
$exePath = [System.IO.Path]::GetFullPath($ExePath)
if (-not (Test-Path $exePath -PathType Leaf)) { throw "Backend executable not found: $exePath" }

$tempRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("RepoMind-Smoke-" + [guid]::NewGuid().ToString("N"))
$appDataRoot = Join-Path $tempRoot "AppData"
$dataDir = Join-Path $appDataRoot "repomind-desktop\backend-data"
$databasePath = Join-Path $dataDir "repomind.sqlite3"
$stdoutPath = Join-Path $tempRoot "backend.stdout.log"
$stderrPath = Join-Path $tempRoot "backend.stderr.log"
$sessionId = [guid]::NewGuid().ToString("N")
$listener = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Loopback, 0)
$listener.Start()
$port = ([System.Net.IPEndPoint] $listener.LocalEndpoint).Port
$listener.Stop()
$backendProcess = $null

try {
    New-Item -ItemType Directory -Force -Path $dataDir | Out-Null
    $environmentValues = @{
        APPDATA = $appDataRoot
        REPOMIND_PATHS__DATA_DIR = $dataDir
        REPOMIND_PATHS__DATABASE_PATH = $databasePath
        REPOMIND_INSTANCE_ID = "repomind-desktop-backend"
        REPOMIND_SESSION_ID = $sessionId
        REPOMIND_PORT = [string] $port
        REPOMIND_LLM_API_KEY = ""
        REPOMIND_EMBEDDING_API_KEY = ""
        OPENAI_API_KEY = ""
    }
    foreach ($environmentItem in $environmentValues.GetEnumerator()) {
        [System.Environment]::SetEnvironmentVariable($environmentItem.Key, $environmentItem.Value, "Process")
    }

    $backendProcess = Start-Process -FilePath $exePath -PassThru -NoNewWindow -RedirectStandardOutput $stdoutPath -RedirectStandardError $stderrPath
    $healthUri = "http://127.0.0.1:$port/api/v1/health"
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    $health = $null
    while ((Get-Date) -lt $deadline) {
        if ($backendProcess.HasExited) {
            $stderrText = if (Test-Path $stderrPath) { Get-Content $stderrPath -Raw } else { "" }
            throw "Backend exited early with code $($backendProcess.ExitCode): $stderrText"
        }
        try {
            $health = Invoke-RestMethod -Uri $healthUri -TimeoutSec 2
            break
        }
        catch {
            Start-Sleep -Milliseconds 250
        }
    }
    if ($null -eq $health) { throw "Timed out waiting for backend health: $healthUri" }
    if ($health.status -ne "ok") { throw "Backend health status is not ok" }
    if ($health.instance_id -ne "repomind-desktop-backend") { throw "Backend identity mismatch" }
    if ($health.api_version -ne "v1") { throw "Backend API version mismatch" }
    if ([int] $health.database_schema_version -ne 7) { throw "Database schema is not version 7" }
    if ($health.session_id -ne $sessionId) { throw "Backend session identity mismatch" }
    if ([System.IO.Path]::GetFullPath([string] $health.database_path) -ne [System.IO.Path]::GetFullPath($databasePath)) {
        throw "Backend used an unexpected database path"
    }

    $pythonCommand = if (Get-Command py -ErrorAction SilentlyContinue) { "py" } else { "python" }
    $databaseCheckPath = Join-Path $tempRoot "verify_database.py"
    $databaseCheck = @'
import sqlite3
import sys

connection = sqlite3.connect(sys.argv[1])
assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
versions = [row[0] for row in connection.execute("SELECT version FROM schema_migrations ORDER BY version")]
assert versions == [1, 2, 3, 4, 6, 7], versions
connection.execute("CREATE VIRTUAL TABLE temp.smoke_fts USING fts5(content)")
connection.execute("INSERT INTO smoke_fts(content) VALUES ('repomind frozen lexical needle')")
assert connection.execute("SELECT count(*) FROM smoke_fts WHERE smoke_fts MATCH 'needle'").fetchone()[0] == 1
for table in ("evidence_fts", "agent_traces", "agent_trace_steps"):
    assert connection.execute("SELECT 1 FROM sqlite_master WHERE name = ?", (table,)).fetchone(), table
print("schema=7 fts5=ok migrations=" + ",".join(map(str, versions)))
'@
    # Windows PowerShell 5.1 may alter quotes passed through `python -c`, so use a temporary script file.
    [System.IO.File]::WriteAllText($databaseCheckPath, $databaseCheck, [System.Text.UTF8Encoding]::new($false))
    & $pythonCommand $databaseCheckPath $databasePath
    if ($LASTEXITCODE -ne 0) { throw "Database migration or FTS5 verification failed" }

    $publicSettings = Invoke-RestMethod -Uri "http://127.0.0.1:$port/api/v1/settings" -TimeoutSec 5
    if ($publicSettings.llm_api_key_configured -or $publicSettings.embedding_api_key_configured) {
        throw "No-key smoke unexpectedly found a configured API key"
    }
    Write-Host "Frozen backend smoke OK: port=$port schema=7 fts5=ok no-key=ok"
}
finally {
    $cleanupFailure = $null
    if ($backendProcess) {
        # 只终止记录到的后端 PID，不递归处理任何父子进程。
        try { Stop-Process -Id $backendProcess.Id -Force -ErrorAction SilentlyContinue } catch { }

        # 只等待刚才记录的后端进程退出；不扫描或终止其他 PID。
        $cleanupDeadline = (Get-Date).AddSeconds(8)
        while (-not $backendProcess.HasExited -and (Get-Date) -lt $cleanupDeadline) {
            Start-Sleep -Milliseconds 200
            $backendProcess.Refresh()
        }

        if (-not $backendProcess.HasExited) {
            $cleanupFailure = "Backend process did not exit cleanly: PID $($backendProcess.Id)"
        }
        else {
            # Open the executable exclusively to confirm that no process still holds a file lock.
            try {
                $lockProbe = [System.IO.File]::Open(
                    $exePath,
                    [System.IO.FileMode]::Open,
                    [System.IO.FileAccess]::Read,
                    [System.IO.FileShare]::None
                )
                $lockProbe.Dispose()
            }
            catch {
                $cleanupFailure = "Backend executable is still locked after smoke: $exePath"
            }
        }
    }
    foreach ($environmentKey in @("APPDATA", "REPOMIND_PATHS__DATA_DIR", "REPOMIND_PATHS__DATABASE_PATH", "REPOMIND_INSTANCE_ID", "REPOMIND_SESSION_ID", "REPOMIND_PORT", "REPOMIND_LLM_API_KEY", "REPOMIND_EMBEDDING_API_KEY", "OPENAI_API_KEY")) {
        [System.Environment]::SetEnvironmentVariable($environmentKey, $null, "Process")
    }
    if (Test-Path $tempRoot) { Remove-Item -Recurse -Force $tempRoot -ErrorAction SilentlyContinue }
    if ($cleanupFailure) { throw $cleanupFailure }
}
