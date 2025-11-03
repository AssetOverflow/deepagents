#!/usr/bin/env pwsh
<#
.SYNOPSIS
  Invoke the Implementer agent in GitHub Copilot CLI
.EXAMPLE
  ./copilot-implement.ps1 "Implement feature X"
#>
param([string[]]$Args)
copilot /agent implementer @Args
