param(
  [Parameter(Mandatory)][string]$RuntimeDirectory,
  [Parameter(Mandatory)][string]$PlatformContext,
  [Parameter(Mandatory)][string]$WebContext,
  [Parameter(Mandatory)][string]$SourcesContext,
  [ValidateRange(1024, 65535)][int]$Port = 8081
)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$local = Join-Path $root '.local'
$private = Join-Path $local 'private'
$runtimeSource = Join-Path $RuntimeDirectory 'runtime.env'
$realmSource = Join-Path $RuntimeDirectory 'keycloak/realm.json'
$record = Join-Path $private 'agent-owner.json'
$config = Join-Path $local 'credentials.env'
if (-not $IsWindows) { throw 'This personal setup requires Windows private ACL support' }
if (-not (Test-Path -LiteralPath $runtimeSource) -or -not (Test-Path -LiteralPath $realmSource)) {
  throw 'Restore the existing paired runtime/realm before configuring credentials'
}
function Protect-PrivatePath([string]$path, [bool]$directory) {
  $identity = [Security.Principal.WindowsIdentity]::GetCurrent().User
  $system = [Security.Principal.SecurityIdentifier]::new('S-1-5-18')
  # Modify DACL only; do not request SACL/owner privileges from a non-admin process.
  $acl = Get-Acl -LiteralPath $path
  if ($acl.GetOwner([Security.Principal.SecurityIdentifier]) -ne $identity) { throw 'Private path owner differs from the current user' }
  $acl.SetAccessRuleProtection($true, $false)
  foreach ($rule in @($acl.Access)) { $acl.RemoveAccessRuleSpecific($rule) }
  foreach ($sid in @($identity, $system)) {
    if ($directory) {
      $rule = [Security.AccessControl.FileSystemAccessRule]::new($sid, 'FullControl', 'ContainerInherit,ObjectInherit', 'None', 'Allow')
    } else { $rule = [Security.AccessControl.FileSystemAccessRule]::new($sid, 'FullControl', 'Allow') }
    $acl.AddAccessRule($rule)
  }
  if ($directory) {
    [IO.FileSystemAclExtensions]::SetAccessControl([IO.DirectoryInfo]::new($path), $acl)
  } else {
    [IO.FileSystemAclExtensions]::SetAccessControl([IO.FileInfo]::new($path), $acl)
  }
}
New-Item -ItemType Directory -Force -Path $private | Out-Null
Protect-PrivatePath $private $true
$values = @{}
foreach ($line in [IO.File]::ReadAllLines($runtimeSource)) {
  if ($line -match '^([^#=]+)=(.*)$') { $values[$matches[1]] = $matches[2] }
}
if ($values['ARCHGUARD_LOCAL_PORT'] -ne "$Port") { throw 'Port differs from the existing OIDC deployment' }
foreach ($context in @($PlatformContext, $WebContext, $SourcesContext)) {
  if (-not (Test-Path -LiteralPath $context -PathType Container) -or $context.Contains("`n") -or $context.Contains("`r")) {
    throw 'Invalid fixed application/source context'
  }
}
$token = $null
$phase = 'admin-login'
try {
  $token = Invoke-RestMethod -Uri "http://localhost:$Port/auth/realms/master/protocol/openid-connect/token" -Method Post -Body @{
    client_id='admin-cli'; username='admin'; password=$values['ARCHGUARD_LOCAL_KEYCLOAK_ADMIN_PASSWORD']; grant_type='password'
  } -TimeoutSec 20
  $headers = @{Authorization = ('Bearer ' + $token.access_token)}
  $admin = "http://localhost:$Port/auth/admin/realms/archguard"
  $phase = 'owner-inventory'
  $response = Invoke-RestMethod -Uri "$admin/users?username=agent-owner&exact=true" -Headers $headers -TimeoutSec 20
  $users = @(); foreach ($item in $response) { $users += $item }
  if (Test-Path -LiteralPath $record) {
    $phase = 'existing-owner-confirmation'
    Protect-PrivatePath $record $false
    $owner = [IO.File]::ReadAllText($record) | ConvertFrom-Json
    if ($users.Count -ne 1 -or $users[0].id -ne $owner.id -or -not $users[0].enabled) { throw 'Owner mismatch' }
  } else {
    $phase = 'new-owner-preconditions'
    if ($users.Count -ne 0 -or (Test-Path -LiteralPath $config)) { throw 'Existing owner state must not be overwritten' }
    $buffer = [byte[]]::new(24)
    [Security.Cryptography.RandomNumberGenerator]::Fill($buffer)
    $owner = [ordered]@{id=[guid]::NewGuid().ToString(); username='agent-owner'; password=[Convert]::ToHexString($buffer); passwordState='initial-temporary'}
    [Array]::Clear($buffer)
    # Persist private recovery record before external write; never print a password/token.
    [IO.File]::WriteAllText($record, ($owner | ConvertTo-Json), [Text.UTF8Encoding]::new($false))
    Protect-PrivatePath $record $false
    $phase = 'owner-creation'
    $body = @{
      id=$owner.id; username=$owner.username; enabled=$true; emailVerified=$true;
      email='agent-owner@localhost.invalid'; firstName='Personal'; lastName='Owner';
      requiredActions=@('UPDATE_PASSWORD');
      credentials=@(@{type='password'; value=$owner.password; temporary=$true})
    }
    Invoke-RestMethod -Uri "$admin/users" -Method Post -Headers $headers -ContentType 'application/json' -Body ($body | ConvertTo-Json -Depth 8) -TimeoutSec 20 | Out-Null
    # Keycloak assigns the canonical UUID; the supplied create DTO id is not authoritative.
    $phase = 'new-owner-confirmation'
    $response = Invoke-RestMethod -Uri "$admin/users?username=agent-owner&exact=true" -Headers $headers -TimeoutSec 20
    $confirmed = @(); foreach ($item in $response) { $confirmed += $item }
    if ($confirmed.Count -ne 1 -or -not $confirmed[0].enabled -or $confirmed[0].email -ne $body.email) { throw 'Owner creation unconfirmed' }
    $owner.id = ([guid]$confirmed[0].id).ToString()
    $body.id = $owner.id
    [IO.File]::WriteAllText($record, ($owner | ConvertTo-Json), [Text.UTF8Encoding]::new($false))
    $phase = 'realm-preservation'
    # Preserve the same UUID on dev-Keycloak re-import; never alter existing users.
    Protect-PrivatePath $realmSource $false
    $realm = [IO.File]::ReadAllText($realmSource) | ConvertFrom-Json
    if (@($realm.users | Where-Object {$_.username -eq 'agent-owner' -or $_.id -eq $owner.id}).Count -ne 0) { throw 'Realm owner conflict' }
    $realm.users = @($realm.users) + $body
    [IO.File]::WriteAllText($realmSource, ($realm | ConvertTo-Json -Depth 30), [Text.UTF8Encoding]::new($false))
  }
  $phase = 'deployment-config'
  if (Test-Path -LiteralPath $config) {
    $existing = [IO.File]::ReadAllText($config)
    if (-not $existing.Contains("ARCHGUARD_CREDENTIAL_OWNER_ID=$($owner.id)")) { throw 'Deployment owner mismatch' }
    Write-Output 'Existing dedicated owner/configuration retained; no credential rotation.'
  } else {
    $deployment = [guid]::NewGuid().ToString()
    $lines = @(
      "ARCHGUARD_CREDENTIAL_OWNER_ID=$($owner.id)",
      "ARCHGUARD_CREDENTIAL_DEPLOYMENT_ID=$deployment",
      'ARCHGUARD_CREDENTIAL_MANAGEMENT_ENABLED=true',
      'ARCHGUARD_CREDENTIAL_UI_ENABLED=true',
      "ARCHGUARD_PLATFORM_CONTEXT=$($PlatformContext.Replace('\','/'))",
      "ARCHGUARD_WEB_CONTEXT=$($WebContext.Replace('\','/'))",
      "ARCHGUARD_SOURCES_CONTEXT=$($SourcesContext.Replace('\','/'))"
    )
    [IO.File]::WriteAllLines($config, $lines, [Text.UTF8Encoding]::new($false))
  }
  # Copy paired existing configuration only on first preparation. Never rotate DB/OIDC.
  New-Item -ItemType Directory -Force -Path (Join-Path $local 'keycloak') | Out-Null
  $phase = 'paired-runtime-copy'
  foreach ($pair in @(@($runtimeSource, (Join-Path $local 'runtime.env')), @($realmSource, (Join-Path $local 'keycloak/realm.json')))) {
    if (-not (Test-Path -LiteralPath $pair[1])) { Copy-Item -LiteralPath $pair[0] -Destination $pair[1]; Protect-PrivatePath $pair[1] $false }
  }
  Write-Output "Dedicated OIDC owner confirmed: agent-owner / $($owner.id)"
  Write-Output 'Private login record: .local/private/agent-owner.json (never share or commit).'
  Write-Output 'Configuration prepared. Bootstrap/check volumes before enabling applications; no model call made.'
} catch {
  throw "Personal owner preparation failed at $phase; sensitive details suppressed. Inspect state privately; do not delete or rotate existing state."
} finally {
  $token = $null; $headers = $null; $body = $null; $owner = $null; $values.Clear()
}
