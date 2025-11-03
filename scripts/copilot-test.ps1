#!/usr/bin/env pwsh
<#
.SYNOPSIS
  Invoke the Tester agent in GitHub Copilot CLI
.EXAMPLE
  ./copilot-test.ps1 "parser module"
#>
param([string[]]$Args)
copilot /agent tester @Args
