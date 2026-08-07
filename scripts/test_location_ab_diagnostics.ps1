$ErrorActionPreference = "Stop"

$helper = Join-Path $PSScriptRoot "location_ab_diagnostics.ps1"
. $helper

$cases = @(
    @{ name = "provider network unavailable"; trace = ""; error = "error sending request for url (https://api.openai.com/v1/responses): os error 10013"; expected = "provider_network_unavailable" },
    @{ name = "502 error"; trace = ""; error = "upstream returned HTTP 502"; expected = "upstream_http_502_or_503" },
    @{ name = "503 error"; trace = ""; error = "status_code=503"; expected = "upstream_http_502_or_503" },
    @{ name = "proxy refused"; trace = ""; error = "proxy connection refused at 127.0.0.1:7890"; expected = "proxy_connection_failure" },
    @{ name = "rate limit"; trace = ""; error = "provider rate limit: 429"; expected = "provider_rate_limit" },
    @{ name = "auth"; trace = ""; error = "401 unauthorized"; expected = "provider_authentication_failure" },
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
