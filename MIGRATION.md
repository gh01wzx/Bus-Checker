# Restore Bus-Checker on another computer

Auckland bus reliability dashboard. Live collection needs your own Auckland Transport API key; old observation history is not included in source control.

## Windows 10/11 x64

Clone this private repository while signed into GitHub. Double-click `Setup.cmd`, then `Start.cmd`.
The setup uses Python 3.11; it can install Python using Windows Package Manager when missing.

## macOS 14 or later (Apple silicon)

Install Python 3.11 with Tk (the universal2 installer from python.org), or install Homebrew.
Run `bash Setup.command` once, then `bash Start.command`. With Homebrew, setup can install Python and Tk.
Apple silicon is the Mac target for current machine-learning wheels. Intel Mac support depends on upstream wheels.
These Mac paths have been reviewed but have not been executed on a Mac.

## Downloads and reproducibility

The first setup requires internet and free disk space for dependencies and models. Every model/resource URL,
fixed revision and SHA-256 is in `resources.json`. Re-running setup reuses files that pass verification and retries
missing or corrupt files. Do not change model revisions to `main` or `latest` when restoring this version.
`python setup.py --check` verifies external resources. `--resources-only` only downloads resources.
Dependencies are pinned; platform-specific runtime wheels can differ while the tool source and models stay the same.
GPU/CPU numerical results and speed can differ across hardware.

The source repository excludes virtual environments, binaries, model weights, recordings, generated files and secrets.
Downloaded native tools and model files are never committed. Packaged runnable apps belong only in GitHub Releases.
Personal outputs, history, cookies and private recordings require your separate private backup; cloning restores the tool.

## Validation scope

Windows checks and resource verification are recorded in VALIDATION.md. Mac startup/install paths are implemented, but no Mac machine was available for runtime verification.

The verified Windows dependency set is frozen in `requirements-lock-windows.txt`; macOS uses pinned cross-platform requirements and its native PyTorch wheels.
