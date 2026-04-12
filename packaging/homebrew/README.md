Homebrew packaging notes for Henio Agent.

Use `packaging/homebrew/henio-agent.rb` as the current tap starting point (legacy filename retained for compatibility) or `homebrew-core` as a reference.

Key choices:
- Stable builds should target the semver-named sdist asset attached to each GitHub release, not the CalVer tag tarball.
- `faster-whisper` now lives in the `voice` extra, which keeps wheel-only transitive dependencies out of the base Homebrew formula.
- The wrapper exports `HENIO_BUNDLED_SKILLS`, `HENIO_OPTIONAL_SKILLS`, and `HENIO_MANAGED=homebrew` so packaged installs keep runtime assets and defer upgrades to Homebrew.

Typical update flow:
1. Bump the formula `url`, `version`, and `sha256`.
2. Refresh Python resources with `brew update-python-resources --print-only henio-agent`.
3. Keep `ignore_packages: %w[certifi cryptography pydantic]`.
4. Verify `brew audit --new --strict henio-agent` and `brew test henio-agent`.
