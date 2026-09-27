$ErrorActionPreference = 'Stop'
$sourceRoot = Split-Path -Parent $PSScriptRoot
$tempRoot = [System.IO.Path]::GetFullPath([System.IO.Path]::GetTempPath())
$testRoot = Join-Path $tempRoot ('archguard-local-up-test-' + [guid]::NewGuid().ToString('N'))
$resolvedTestRoot = [System.IO.Path]::GetFullPath($testRoot)
if (-not $resolvedTestRoot.StartsWith($tempRoot, [StringComparison]::OrdinalIgnoreCase)) {
  throw 'Temporary test directory escaped the OS temporary directory'
}

try {
  $scripts = New-Item -ItemType Directory -Path (Join-Path $testRoot 'scripts') -Force
  $keycloak = New-Item -ItemType Directory -Path (Join-Path $testRoot 'keycloak') -Force
  Copy-Item -LiteralPath (Join-Path $sourceRoot 'scripts/local-up.ps1') -Destination $scripts.FullName
  Copy-Item -LiteralPath (Join-Path $sourceRoot 'keycloak/realm.template.json') -Destination $keycloak.FullName
  $global:archguardTestDockerCalls = 0
  function global:docker {
    $global:archguardTestDockerCalls++
    $global:LASTEXITCODE = 0
  }

  $localUp = Join-Path $scripts.FullName 'local-up.ps1'
  & $localUp 6>$null | Out-Null
  $runtime = Join-Path $testRoot '.local/runtime.env'
  $realm = Join-Path $testRoot '.local/keycloak/realm.json'
  if (-not (Test-Path -LiteralPath $runtime) -or -not (Test-Path -LiteralPath $realm)) {
    throw 'First start did not create both local credential files'
  }
  $firstRuntime = (Get-FileHash -LiteralPath $runtime -Algorithm SHA256).Hash
  $firstRealm = (Get-FileHash -LiteralPath $realm -Algorithm SHA256).Hash

  & $localUp 6>$null | Out-Null
  if ((Get-FileHash -LiteralPath $runtime -Algorithm SHA256).Hash -ne $firstRuntime -or
      (Get-FileHash -LiteralPath $realm -Algorithm SHA256).Hash -ne $firstRealm) {
    throw 'Repeated local start rotated credentials for an existing data volume'
  }
  if ($global:archguardTestDockerCalls -ne 2) {
    throw "Expected two Compose starts, got $global:archguardTestDockerCalls"
  }
  Write-Output 'Local startup credential reuse: PASS'
}
finally {
  Remove-Item Function:\docker -ErrorAction SilentlyContinue
  Remove-Variable archguardTestDockerCalls -Scope Global -ErrorAction SilentlyContinue
  if (Test-Path -LiteralPath $resolvedTestRoot) {
    Remove-Item -LiteralPath $resolvedTestRoot -Recurse -Force
  }
}
