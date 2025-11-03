#!/usr/bin/env pwsh
<#
.SYNOPSIS
  Invoke the Ops agent in GitHub Copilot CLI
.EXAMPLE
  ./copilot-ops.ps1 "Add Redis service"
#>
param([string[]]$Args)
copilot /agent ops @Args
