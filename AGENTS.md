# FSR XMX Proton bridge

Experimental compatibility research, not a working bridge yet.

## Safety boundaries
- Static analysis is the default. Never execute downloaded DLLs or setup scripts as part of inspection.
- Do not modify Steam, Proton prefixes, system/session environment, drivers or services without explicit user approval.
- Runtime experiments require a disposable prefix and narrowly scoped driver environment; never start with the production game prefix.
- Do not call a test successful based only on S_OK, an overlay label, or shader creation. Require actual injection evidence and deterministic GPU readback.
- Keep original archives immutable in artifacts/original; extract only into artifacts/extracted.
- Third-party DLLs/models and upstream source checkouts are ignored by this repository. Do not redistribute them or claim licensing rights.
- Do not disable driver canaries or hide compilation failures to make tests pass.

## Commit convention
- Use Conventional Commits with an English subject: `type(scope): Description`.
- Choose a type matching the change, such as `feat`, `fix`, `docs`, `refactor`, `test`, `build`, `ci`, or `chore`.
- Use a concise scope identifying the affected area, such as `artifact`, `shim`, `tools`, or `docs`.
- Keep each commit focused; explain motivation and relevant limitations in the body when needed.
- Example: `fix(artifact): The DLL of XeSS is not present in Linux (only in windows)`.

## Structure
- docs/: evidence, ABI mapping, experiment plans.
- tools/: local static-analysis utilities (standard library where possible).
- artifacts/: local-only archives and extracted DLLs.
- upstream/xess-xmx-linux/: independent upstream checkout; record exact revision for reproducibility.
- analysis/: generated local reports.

Use the project's README and docs/compatibility.md before implementing changes.
