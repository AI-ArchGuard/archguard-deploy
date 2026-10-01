param([ValidateRange(1024, 65535)][int]$Port = 8080)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$local = Join-Path $root '.local'
$keycloak = Join-Path $local 'keycloak'
New-Item -ItemType Directory -Force -Path $keycloak | Out-Null
$runtimeFile = Join-Path $local 'runtime.env'
$realmFile = Join-Path $keycloak 'realm.json'
$hasRuntime = Test-Path -LiteralPath $runtimeFile
$hasRealm = Test-Path -LiteralPath $realmFile
if ($hasRuntime -ne $hasRealm) {
  throw 'Local credential state is incomplete; restore the missing file before starting Compose'
}
function New-Secret([int]$bytes = 24) {
  $buffer = New-Object byte[] $bytes
  [System.Security.Cryptography.RandomNumberGenerator]::Fill($buffer)
  return [Convert]::ToHexString($buffer).ToLowerInvariant()
}
if (-not $hasRuntime) {
  $db = New-Secret
  $admin = New-Secret
  $demo = New-Secret 12
  $webhook = New-Secret 32
@"
ARCHGUARD_LOCAL_DB_PASSWORD=$db
ARCHGUARD_LOCAL_KEYCLOAK_ADMIN_PASSWORD=$admin
ARCHGUARD_GITHUB_WEBHOOK_SECRET=$webhook
ARCHGUARD_LOCAL_PORT=$Port
"@ | Set-Content -LiteralPath $runtimeFile -Encoding utf8NoBOM
  $template = Get-Content -LiteralPath (Join-Path $root 'keycloak/realm.template.json') -Raw
  $template.Replace('__DEMO_USER_PASSWORD__', $demo).Replace('localhost:8080', "localhost:$Port") | Set-Content -LiteralPath $realmFile -Encoding utf8NoBOM
} else {
  $runtime = Get-Content -LiteralPath $runtimeFile
  $portLine = $runtime | Where-Object { $_ -match '^ARCHGUARD_LOCAL_PORT=' }
  $existingPort = if ($portLine) { [int]($portLine -split '=', 2)[1] } else { 8080 }
  if ($existingPort -ne $Port) {
    throw 'Local port differs from existing credential state; use the original port or a separate checkout'
  }
  $realm = Get-Content -LiteralPath $realmFile -Raw | ConvertFrom-Json
  $maintainer = $realm.users | Where-Object { $_.username -eq 'maintainer' } | Select-Object -First 1
  $demo = $maintainer.credentials | Where-Object { $_.type -eq 'password' } | Select-Object -First 1 -ExpandProperty value
  if ([string]::IsNullOrWhiteSpace($demo)) {
    throw 'Existing local realm has no maintainer password; refusing to rotate credentials'
  }
}
$env:ARCHGUARD_LOCAL_PORT = "$Port"
Write-Host "ArchGuard local user: maintainer"
Write-Host "ArchGuard local password: $demo"
docker compose --project-directory $root --env-file $runtimeFile up --build -d
if ($LASTEXITCODE -ne 0) {
  throw "Compose startup failed with exit code $LASTEXITCODE"
}
