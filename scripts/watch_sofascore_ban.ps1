$url = "https://api.sofascore.com/api/v1/sport/tennis/events/live"
$log = "C:\Users\Victor\Downloads\polymarket_bot (1)\polymarket_bot\data\sofascore_ban.log"
$deadline = (Get-Date).AddHours(3)
while ((Get-Date) -lt $deadline) {
    $code = curl.exe -s -o NUL -w "%{http_code}" -H "User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36" $url
    $line = "$(Get-Date -Format o) $code"
    Add-Content -Path $log -Value $line
    if ($code -eq "200") {
        Add-Content -Path $log -Value "BAN CLEARED 200 OK"
        break
    }
    Start-Sleep -Seconds 300
}