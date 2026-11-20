# Validation

Verified on Windows x64 with Python 3.11 on 2026-11-20.

- Fresh Windows dependency environment installed; pip check passed.
- 17 existing unit tests passed.
- Temporary warehouse integration checks passed: initial/incremental builds, reconciliation and dashboard pages.
- Setup downloaded current public GTFS references and built all 16 models; 27 dbt tests passed.
- The personal observation database and API credentials were not included.

## Mac scope

Setup/launch shell syntax passed. Required pinned packages were checked for macOS 14 Apple silicon availability; pure Python source distributions are allowed.
No Mac was available: native UI, audio, model inference and MPS acceleration have **not** been executed on macOS.
The VoiceClone default is CPU on Mac; MPS is an explicit experimental option.

## Resource scope

Upstream resource URLs were checked. Functional tests reused locally available model files only after matching the source manifest hashes, rather than re-downloading every multi-gigabyte model.
The downloader was separately exercised on a fresh directory and on a corrupted file. Source repositories do not contain the downloaded model weights or native executables.
