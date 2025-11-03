#!/usr/bin/env pwsh
<#
.SYNOPSIS
  Run a full Copilot dev cycle with feedback loops:
  Planner → Implementer → Reviewer → Tester → Ops
.DESCRIPTION
  This script orchestrates all Copilot agents in sequence for a given feature or change.
  If Reviewer or Tester detect failures, their feedback is passed back to Implementer
  (and Planner/Ops if needed) until all checks pass.
  Logs are written to ./scripts/devcycle.log.
.EXAMPLE
  ./copilot-devcycle.ps1 "Add a new health check endpoint"
#>

param(
    [Parameter(Mandatory=$true, Position=0)]
    [string]$Goal
)

$logFile = Join-Path $PSScriptRoot "devcycle.log"

function Log-Step {
    param([string]$Step, [string]$Command)
    Write-Host "🚀 Running $Step..."
    Add-Content -Path $logFile -Value "`n=== $Step ==="
    Add-Content -Path $logFile -Value "Command: $Command"
    $output = Invoke-Expression $Command 2>&1
    $output | Tee-Object -FilePath $logFile -Append
    Write-Host "✅ $Step complete."
    return $output -join "`n"
}

# Clear old log
if (Test-Path $logFile) { Remove-Item $logFile }

Write-Host "🔧 Starting Copilot Dev Cycle for: $Goal"
Add-Content -Path $logFile -Value "Dev Cycle for: $Goal"

# Step 1: Planner
$planOutput = Log-Step "Planner" "copilot /agent planner `"$Goal`""

# Step 2: Implementer
$implOutput = Log-Step "Implementer" "copilot /agent implementer `"$Goal`""

# Feedback loop for Reviewer + Tester
$maxIterations = 5
for ($i = 1; $i -le $maxIterations; $i++) {
    Write-Host "🔄 Iteration $i of review/test loop"

    # Step 3: Reviewer
    $reviewOutput = Log-Step "Reviewer" "copilot /agent reviewer `"$Goal`""

    if ($reviewOutput -match "PASS" -or $reviewOutput -match "No issues") {
        Write-Host "✅ Reviewer passed."
    } else {
        Write-Host "❌ Reviewer found issues. Sending back to Implementer..."
        $implOutput = Log-Step "Implementer (fixes)" "copilot /agent implementer `"$reviewOutput`""
        continue
    }

    # Step 4: Tester
    $testOutput = Log-Step "Tester" "copilot /agent tester `"$Goal`""

    if ($testOutput -match "PASS" -or $testOutput -match "All tests passed") {
        Write-Host "✅ Tester passed."
        break
    } else {
        Write-Host "❌ Tests failed. Sending back to Implementer..."
        $implOutput = Log-Step "Implementer (fixes)" "copilot /agent implementer `"$testOutput`""
    }
}

# Step 5: Ops
$opsOutput = Log-Step "Ops" "copilot /agent ops `"$Goal`""

Write-Host "🎉 Dev cycle complete. See $logFile for full transcript."
