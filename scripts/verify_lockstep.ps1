Param(
  [string]$RepoDir = "."
)

$ErrorActionPreference = "Stop"

Set-Location $RepoDir

Write-Host "== Lockstep Verification ==" -ForegroundColor Cyan
Write-Host "Repo: $(Get-Location)"
Write-Host ""

Write-Host "[1/6] Git status"
git status -sb
Write-Host ""

Write-Host "[2/6] Git remote"
git remote -v
Write-Host ""

Write-Host "[3/6] GitHub SSH auth"
try {
  ssh -T git@github.com
} catch {
  # GitHub returns non-zero after success banner; keep output visible.
}
Write-Host ""

Write-Host "[4/6] Remote HEAD"
git ls-remote origin HEAD
Write-Host ""

Write-Host "[5/6] Jenkins trigger env vars"
$vars = @("JENKINS_TRIGGER_URL", "JENKINS_USER", "JENKINS_API_TOKEN")
foreach ($v in $vars) {
  $val = [Environment]::GetEnvironmentVariable($v, "User")
  if ([string]::IsNullOrWhiteSpace($val)) {
    Write-Host "  $v = <not set>" -ForegroundColor Yellow
  } else {
    if ($v -eq "JENKINS_API_TOKEN") {
      Write-Host "  $v = <set>" -ForegroundColor Green
    } else {
      Write-Host "  $v = $val" -ForegroundColor Green
    }
  }
}
Write-Host ""

Write-Host "[6/6] Jenkins trigger script dry-run"
python .\scripts\trigger_jenkins.py
Write-Host ""

Write-Host "Lockstep verification complete." -ForegroundColor Cyan
