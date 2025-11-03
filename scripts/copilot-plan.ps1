#!/usr/bin/env pwsh
<#
.SYNOPSIS
  Invoke the Planner agent in GitHub Copilot CLI
.EXAMPLE
  ./copilot-plan.ps1 "Add a new endpoint"
#>
param([string[]]$Args)
copilot /agent planner @Args
