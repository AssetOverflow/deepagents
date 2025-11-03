import os
import textwrap

# Define the PowerShell scripts we want to generate
SCRIPTS = {
    "copilot-plan.ps1": """#!/usr/bin/env pwsh
<#
.SYNOPSIS
  Invoke the Planner agent in GitHub Copilot CLI
.EXAMPLE
  ./copilot-plan.ps1 "Add a new endpoint"
#>
param([string[]]$Args)
copilot /agent planner @Args
""",
    "copilot-implement.ps1": """#!/usr/bin/env pwsh
<#
.SYNOPSIS
  Invoke the Implementer agent in GitHub Copilot CLI
.EXAMPLE
  ./copilot-implement.ps1 "Implement feature X"
#>
param([string[]]$Args)
copilot /agent implementer @Args
""",
    "copilot-review.ps1": """#!/usr/bin/env pwsh
<#
.SYNOPSIS
  Invoke the Reviewer agent in GitHub Copilot CLI
.EXAMPLE
  ./copilot-review.ps1 src/
#>
param([string[]]$Args)
copilot /agent reviewer @Args
""",
    "copilot-test.ps1": """#!/usr/bin/env pwsh
<#
.SYNOPSIS
  Invoke the Tester agent in GitHub Copilot CLI
.EXAMPLE
  ./copilot-test.ps1 "parser module"
#>
param([string[]]$Args)
copilot /agent tester @Args
""",
    "copilot-ops.ps1": """#!/usr/bin/env pwsh
<#
.SYNOPSIS
  Invoke the Ops agent in GitHub Copilot CLI
.EXAMPLE
  ./copilot-ops.ps1 "Add Redis service"
#>
param([string[]]$Args)
copilot /agent ops @Args
"""
}


def write_script(path, content):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(textwrap.dedent(content))
    print(f"✅ Created {path}")


def main():
    print("🚀 Setting up Copilot agent wrapper scripts for PowerShell...\n")

    scripts_dir = "scripts"
    os.makedirs(scripts_dir, exist_ok=True)

    for name, content in SCRIPTS.items():
        path = os.path.join(scripts_dir, name)
        write_script(path, content)

    print("\n🎉 Done! All PowerShell wrapper scripts created in ./scripts/")
    print("Next steps:")
    print("1. Add ./scripts to your PATH in PowerShell profile, e.g.:")
    print("   $env:PATH += ';' + (Resolve-Path './scripts')")
    print("2. Then you can run commands like:")
    print("   ./scripts/copilot-plan.ps1 \"Add a new endpoint\"")
    print("   ./scripts/copilot-implement.ps1 \"Implement health check\"")
    print("   ./scripts/copilot-review.ps1 src/")
    print("   ./scripts/copilot-test.ps1 \"parser module\"")
    print("   ./scripts/copilot-ops.ps1 \"Add Redis service\"")


if __name__ == "__main__":
    main()
