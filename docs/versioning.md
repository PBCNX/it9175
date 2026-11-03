# Versioning and releases

## Where the number lives

`pyproject.toml` (`version`), `it9175/__init__.py` (`__version__`), the
`vX.Y.Z` tag and `CHANGELOG.md` must agree. The Java core
(`it9175/java/build.gradle`) and the Android demo (`versionName`) carry the same
number. SemVer: patch for fixes and docs, minor for a compatible feature or a
newly measured platform, `1.0.0` only when the API and the platform matrix are
stable and honest.

## Repository roles

```text
main              full working tree: code, tests, firmware, vendor DLL,
                  internal docs and RE tools.  This is where we work.
public-mirror     curated release branch: truncated and edited for the public,
                  audited.  This is what we publish.
public remote     PBCNX/it9175; receives public-mirror only, never main
```

`main` deliberately carries everything, including the vendor firmware, the
bundled libusb DLL and the private prose. It is the test bed. `public-mirror`
is not a rebuild of main: it is a long-lived branch with hand edits (README
trimmed, private docs dropped) and those edits are preserved between releases.
Never regenerate the mirror from main blindly; sync main into it and keep the
curation.

## The public mirror

Withhold from `main` when syncing:

- `it9175/firmware.bin`, `firmware/`, `*.inp`, `*.pcap`, `*.ts`, `*.fw`;
- `vendor/windows/` — the bundled libusb DLL is private-tree only; public users
  install libusb and set `IT9175_LIBUSB`;
- `START-HERE.md` and `release.ps1` — internal handoff and release tooling;
- development/reverse-engineering tooling (`tools/gen_*`,
  `tools/java_math_check.py`, `tools/fetch_deps.py`, `tools/pi_*.sh`);
  user-facing `preflight`, `ts_check`, `ts_cc`, `send_ts` stay;
- `docs/testing.md`, `docs/vendor-api.md`, `docs/compatibility.md` — private
  working notes. The public docs set is `INSTALL.md`, `docs/protocol.md`,
  `docs/verification.md`, `docs/versioning.md`, plus the trimmed README;
- `.tmp/`, `__pycache__/`, `*.pyc`, APKs.

Audit the mirror branch before any release; a hit blocks the push. Review, in
order:

- the full file list and count (`git ls-tree -r --name-only public-mirror`);
- no firmware or vendor binary names (`firmware`, `.dll`, `.so`, `.class`,
  `.apk`, `.exe`; `firmware.py` is code and stays);
- no absolute drive or home paths, no usernames, no local IP addresses;
- no private remote names (the `-prv` repositories), no private-key headers, no
  GitHub-token or AWS-key shapes;
- every relative markdown link resolves inside the mirror tree.

## Release order

1. `main` clean; tests pass (Python `unittest`, Java `SelfTest`).
2. `public-mirror` curated and audited.
3. The owner says **release** and the version.
4. Publish the curated tree as a **single orphan commit** (no mirror history, so
   older mirror snapshots cannot serve removed files by SHA): `release.ps1`
   builds it from `public-mirror^{tree}` and pushes it to `main`. A fresh repo
   takes it; an existing one needs a fast-forward or `-Force` on the word.
5. Probe the old public SHAs (all must 404), then tag `vX.Y.Z` **on that release
   commit** and push the tag.
6. Create a source-only GitHub release (no assets unless asked).
7. Push `main` and the tag to the private testbed.

If a public repo exposed firmware: a force-push does not remove it — GitHub
serves old commits by SHA. Flip it private/rename it away and publish a fresh
repo; verify the old SHAs return 404.

## Artifacts

The tree is source. No APK, DLL, firmware image or capture is committed; builds
stay local. The firmware is supplied by the user (`--firmware PATH` or
`IT9175_FIRMWARE`) and `firmware.image()` checks its SHA-256 before upload.

## Current

- `v0.2.1` — 2026-11-03, licence-only patch: copyright holder is
  **The IT9175 Open Driver Authors**; no code change.
- `v0.2.0` — 2026-11-03, **published; 70-file curated** public snapshot at
  commit `19575fa`, tag `v0.2.0`, source-only release
  (`https://github.com/PBCNX/it9175/releases/tag/v0.2.0`): README trimmed,
  `INSTALL.md` added, public docs `protocol` + `verification` + `versioning`,
  private `testing`/`vendor-api`/`compatibility`; adds the Android demo, the
  Java core proven on a phone, 32,768-byte TS reads, macOS Intel and the
  provenance marker. `main` keeps all of it (84 files).
- `v0.1.1` — 2026-10-23, public snapshot of 64 files. It still carries
  `START-HERE.md` and `release.ps1`.
- `v0.1.0` — 2026-10-23, first public snapshot, also 64 files.
- Unreleased: none.
- Resolved 2026-11-03: the old public repo was flipped private and renamed
  `PBCNX/it9175-archive`. A fresh, empty `PBCNX/it9175` is public. The five
  leak commits are gone from public refs and the archive URL is 404 anonymously;
  the old-name raw URL served from Fastly's cache for a few minutes after the
  flip, then 404s because the new repo has no such object. The first public
  commit is `19575fa` (`v0.2.0`).
