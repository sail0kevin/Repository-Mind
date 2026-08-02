function Get-InfrastructureFailureClass([string]$TracePath, [string]$ErrorPath) {
    $text = ""
    if (Test-Path -LiteralPath $TracePath -PathType Leaf) {
        $text += "`n" + (Get-Content -LiteralPath $TracePath -Raw -Encoding utf8)
    }
    if (Test-Path -LiteralPath $ErrorPath -PathType Leaf) {
        $text += "`n" + (Get-Content -LiteralPath $ErrorPath -Raw -Encoding utf8)
    }

    if ($text -match '(?i)(HTTP\s*50[23]|status[_ ]?code.?[:=]?.?50[23]|upstream.*50[23])') {
        return "upstream_http_502_or_503"
    }
    if ($text -match '(?i)(proxy.*(failed|error|refused)|connection.*(refused|reset)|127\.0\.0\.1:\d+)') {
        return "proxy_connection_failure"
    }
    if ($text -match '(?i)(rate.?limit|too many requests|429)') {
        return "provider_rate_limit"
    }
    if ($text -match '(?i)(unauthorized|authentication|invalid api key|401|403)') {
        return "provider_authentication_failure"
    }
    return $null
}
