$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$local = Join-Path $root '.local'
$keycloak = Join-Path $local 'keycloak'
New-Item -ItemType Directory -Force -Path $keycloak | Out-Null
function New-Secret([int]$bytes = 24) {
  $buffer = New-Object byte[] $bytes
  [System.Security.Cryptography.RandomNumberGenerator]::Fill($buffer)
  return [Convert]::ToHexString($buffer).ToLowerInvariant()
}
$db = New-Secret
$admin = New-Secret
$demo = New-Secret 12
$webhook = New-Secret 32
@"
ARCHGUARD_LOCAL_DB_PASSWORD=$db
ARCHGUARD_LOCAL_KEYCLOAK_ADMIN_PASSWORD=$admin
ARCHGUARD_GITHUB_WEBHOOK_SECRET=$webhook
"@ | Set-Content -LiteralPath (Join-Path $local 'runtime.env') -Encoding utf8NoBOM
$template = Get-Content -LiteralPath (Join-Path $root 'keycloak/realm.template.json') -Raw
$template.Replace('__DEMO_USER_PASSWORD__', $demo) | Set-Content -LiteralPath (Join-Path $keycloak 'realm.json') -Encoding utf8NoBOM
Write-Host "ArchGuard local user: maintainer"
Write-Host "ArchGuard local password: $demo"
docker compose --project-directory $root --env-file (Join-Path $local 'runtime.env') up --build -d
