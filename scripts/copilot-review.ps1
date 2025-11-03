#!/usr/bin/env pwsh
<#
.SYNOPSIS
  Invoke the Reviewer agent in GitHub Copilot CLI
.EXAMPLE
  ./copilot-review.ps1 src/
#>
param([string[]]$Args)
copilot /agent reviewer @Args
