# 2.0.0

Release 2.0.0

Update pagination handling, validation, and documentation.

Changes since 1.0.1:

```text
README.md          | 14 +++++++++++
 pyproject.toml     |  4 ++--
 tnaflix_api/api.py | 68 ++++++++++++++++++++++++++++++++----------------------
 3 files changed, 56 insertions(+), 30 deletions(-)
```

# Changelog

## 1.0.1 — 2026-10-27

- Follow canonical watch links when short or embedded pages omit metadata and related videos.
- Normalize video, profile, channel and pornstar links and return the correct media types.
- Expose callable author and performer helpers and keep channel authors out of tags and categories.
- Parse abbreviated rating counts and source URLs when optional size attributes are absent.
- Export Sort and SortDate and send date sorting through the website query parameter.
- Include the HTML fixtures used by the parser regression tests.
- Use the published `eaf-base-api>=4.2.5` dependency.

