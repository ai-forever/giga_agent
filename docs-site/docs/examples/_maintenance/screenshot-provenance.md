# Historical screenshot provenance

This file documents how example-gallery screenshots are maintained. It is stored under docs maintenance content rather than the public static image tree.

The images in `docs-site/static/img/examples/` are sanitized screenshots derived from historical GigaAgent case runs. They are included as visual illustrations for documentation examples only.

Rules for maintaining these images:

- Do not publish or link the original PDF run logs.
- Do not add screenshots with visible credentials, tokens, DB URLs, webhooks, internal hostnames, thread IDs, raw IP addresses, personal data, or private company data.
- Redact service chrome, URLs, thread identifiers, hostnames, IP addresses, user identifiers, and other environment-specific details before committing.
- Keep example pages aligned with the public PyPI documentation version (`giga-agent==0.1.9`) unless a page explicitly labels a feature as current-main/upcoming.
- Prefer small illustrative galleries over full transcripts.
- Security/log-analysis examples should use synthetic screenshots only.

The current galleries are based on local historical PDFs outside this repository. Those PDFs are not part of the repository and must remain unpublished.
