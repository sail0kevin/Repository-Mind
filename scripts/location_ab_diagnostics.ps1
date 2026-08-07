function Get-InfrastructureFailureClass([string]$TracePath, [string]$ErrorPath) {
    $traceText = ""
    $errorText = ""
    if (Test-Path -LiteralPath $TracePath -PathType Leaf) {
        $traceText = Get-Content -LiteralPath $TracePath -Raw -Encoding utf8
    }
    if (Test-Path -LiteralPath $ErrorPath -PathType Leaf) {
        $errorText = Get-Content -LiteralPath $ErrorPath -Raw -Encoding utf8
    }

    # Do not classify arbitrary repository source text in the trace as provider failure.
    # Codex stderr is the authoritative channel for process/provider diagnostics.
    if ($errorText -match '(?i)(os error 10013|failed to connect to websocket|error sending request for url \(https://api\.openai\.com|wss://api\.openai\.com/v1/responses)') {
        return "provider_network_unavailable"
    }
    if ($errorText -match '(?i)(HTTP\s*50[23]|status[_ ]?code.?[:=]?.?50[23]|upstream.*50[23])') {
        return "upstream_http_502_or_503"
    }
    if ($errorText -match '(?i)(proxy.*(failed|error|refused)|connection.*(refused|reset)|127\.0\.0\.1:\d+)') {
        return "proxy_connection_failure"
    }
    if ($errorText -match '(?i)(rate.?limit|too many requests|429)') {
        return "provider_rate_limit"
    }
    if ($errorText -match '(?i)(unauthorized|authentication|invalid api key|401|403)') {
        return "provider_authentication_failure"
    }
    return $null
}