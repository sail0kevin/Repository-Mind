$ErrorActionPreference = "Stop"

$helper = Join-Path $PSScriptRoot "location_ab_diagnostics.ps1"
. $helper

$cases = @(
    @{ name = "502 trace"; trace = "upstream returned HTTP 502"; error = ""; expected = "upstream_http_502_or_503" },
    @{ name = "503 error"; trace = ""; error = "status_code=503"; expected = "upstream_http_502_or_503" },
    @{ name = "proxy refused"; trace = "proxy connection refused at 127.0.0.1:7890"; error = ""; expected = "proxy_connection_failure" },
    @{ name = "rate limit"; trace = "provider rate limit: 429"; error = ""; expected = "provider_rate_limit" },
    @{ name = "auth"; trace = "401 unauthorized"; error = ""; expected = "provider_authentication_failure" },
    @{ name = "ordinary failure"; trace = "agent_message missing"; error = ""; expected = $null }
)

foreach ($case in $cases) {
    $tracePath = Join-Path $env:TEMP "repomind-diagnostics-$PID-trace.log"
    $errorPath = Join-Path $env:TEMP "repomind-diagnostics-$PID-error.log"
    [System.IO.File]::WriteAllText($tracePath, $case.trace)
    [System.IO.File]::WriteAllText($errorPath, $case.error)
    try {
        $actual = Get-InfrastructureFailureClass $tracePath $errorPath
        if ($actual -ne $case.expected) {
            throw "$($case.name): expected '$($case.expected)', got '$actual'"
        }
    } finally {
        Remove-Item -LiteralPath $tracePath, $errorPath -Force -ErrorAction SilentlyContinue
    }
}

Write-Host "Location A/B infrastructure diagnostics regression passed ($($cases.Count) cases)."
