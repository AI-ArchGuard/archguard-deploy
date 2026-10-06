$ErrorActionPreference = 'Stop'
$sourceRoot = Split-Path -Parent $PSScriptRoot
$temporaryBase = [IO.Path]::GetFullPath([IO.Path]::GetTempPath())
$testRoot = [IO.Path]::GetFullPath((Join-Path $temporaryBase ('archguard-owner-test-' + [guid]::NewGuid().ToString('N'))))
if (-not $testRoot.StartsWith($temporaryBase, [StringComparison]::OrdinalIgnoreCase)) { throw 'Unsafe test path' }
try {
  New-Item -ItemType Directory -Force -Path "$testRoot/scripts", "$testRoot/runtime/keycloak", "$testRoot/context" | Out-Null
  Copy-Item -LiteralPath "$sourceRoot/scripts/configure-personal-owner.ps1" -Destination "$testRoot/scripts/"
  [IO.File]::WriteAllText("$testRoot/runtime/runtime.env", "ARCHGUARD_LOCAL_PORT=8081`nARCHGUARD_LOCAL_KEYCLOAK_ADMIN_PASSWORD=synthetic-test-only`n")
  Copy-Item -LiteralPath "$sourceRoot/keycloak/realm.template.json" -Destination "$testRoot/runtime/keycloak/realm.json"
  $global:archguardOwnerUsers = @()
  $global:archguardOwnerCreates = 0
  function global:Invoke-RestMethod {
    param($Uri, $Method, $Body, $Headers, $ContentType, $TimeoutSec)
    if ($Uri.EndsWith('/token')) { return @{access_token='synthetic-offline-token'} }
    if ($Method -eq 'Post') {
      $value = $Body | ConvertFrom-Json
      if ($value.username -ne 'agent-owner' -or -not $value.credentials[0].temporary -or $value.requiredActions[0] -ne 'UPDATE_PASSWORD') { throw 'Unsafe account' }
      $value.id = [guid]::NewGuid().ToString()
      $global:archguardOwnerUsers = @($value)
      $global:archguardOwnerCreates++
      return
    }
    # REST returns an empty JSON array as a single non-enumerated pipeline object.
    Write-Output -NoEnumerate $global:archguardOwnerUsers
  }
  $setup = "$testRoot/scripts/configure-personal-owner.ps1"
  & $setup -RuntimeDirectory "$testRoot/runtime" -PlatformContext "$testRoot/context" -WebContext "$testRoot/context" -SourcesContext "$testRoot/context" | Out-Null
  $record = "$testRoot/.local/private/agent-owner.json"
  $config = "$testRoot/.local/credentials.env"
  $first = [IO.File]::ReadAllText($config)
  $firstRecord = [IO.File]::ReadAllText($record)
  if (($firstRecord | ConvertFrom-Json).id -ne $global:archguardOwnerUsers[0].id) { throw 'Keycloak canonical UUID not recorded' }
  $realm = [IO.File]::ReadAllText("$testRoot/runtime/keycloak/realm.json") | ConvertFrom-Json
  if (($realm.users | Where-Object {$_.username -eq 'agent-owner'}).id -ne $global:archguardOwnerUsers[0].id) { throw 'Realm canonical UUID mismatch' }
  $acl = Get-Acl -LiteralPath $record
  if (-not $acl.AreAccessRulesProtected -or $acl.Access.Count -ne 2) { throw 'Private owner ACL missing' }
  & $setup -RuntimeDirectory "$testRoot/runtime" -PlatformContext "$testRoot/context" -WebContext "$testRoot/context" -SourcesContext "$testRoot/context" | Out-Null
  if ($first -ne [IO.File]::ReadAllText($config) -or $firstRecord -ne [IO.File]::ReadAllText($record) -or $global:archguardOwnerCreates -ne 1) { throw 'Setup rotated existing identity/state' }
  $global:archguardOwnerUsers[0].id = [guid]::NewGuid().ToString()
  $refused = $false
  try { & $setup -RuntimeDirectory "$testRoot/runtime" -PlatformContext "$testRoot/context" -WebContext "$testRoot/context" -SourcesContext "$testRoot/context" | Out-Null } catch { $refused = $true }
  if (-not $refused -or $global:archguardOwnerCreates -ne 1) { throw 'Mismatched owner not refused' }
  Write-Output 'Offline dedicated owner: private ACL/temporary password/reuse/mismatch refusal PASS'
} finally {
  Remove-Item Function:\Invoke-RestMethod -ErrorAction SilentlyContinue
  Remove-Variable archguardOwnerUsers, archguardOwnerCreates -Scope Global -ErrorAction SilentlyContinue
  if (Test-Path -LiteralPath $testRoot) { Remove-Item -LiteralPath $testRoot -Recurse -Force }
}
