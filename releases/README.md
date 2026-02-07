# Releases

This directory keeps helper scripts and notes for producing standalone binaries of `larksync`.

## Prerequisites

- Python 3.11+ on the target machine (macOS or Windows)
- The Feishu credentials you normally configure in `config.toml`
- Basic build tools (Xcode command-line tools for macOS, Visual Studio Build Tools or the Desktop development workload for Windows if not already installed)

## macOS build

1. Ensure you are on macOS (cross-compiling from Linux or Windows is not supported by PyInstaller).
2. From the repository root, run:

   ```bash
   chmod +x releases/build_mac.sh
   ./releases/build_mac.sh
   ```

3. The resulting universal binary will be placed under `releases/dist-mac/larksync`.

## Windows build

1. Ensure you are on Windows with PowerShell 5+ (or PowerShell Core) and Python available in `PATH`.
2. From the repository root, run:

   ```powershell
   Set-ExecutionPolicy -Scope Process RemoteSigned
   ./releases/build_windows.ps1
   ```

3. The resulting executable will be written to `releases\dist-windows\larksync.exe`.

## Notes

- Both scripts create an isolated virtual environment so they do not touch your global Python installation.
- PyInstaller bundles the CLI with all dependencies; you still need to provide a valid `config.toml` alongside the binary (or point to one via `--config`).
- Re-run the scripts after repository updates to rebuild fresh binaries.
