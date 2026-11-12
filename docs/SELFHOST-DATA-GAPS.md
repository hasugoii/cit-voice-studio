# Validation scope

- `npm ci` reported 8 existing dependency advisories (1 low, 3 moderate, 4 high),
  including dev build tools and zod. No dependency lock changes are included in
  this domain/selfhost change. Assess advisories and compatible updates separately;
  current tests are not a security audit. Evidence: local npm audit 2026-11-12.
- Single-owner, shared model, one API key; no multitenant quotas or independent
  model selection per API caller. Use `/health` and `/voices` before synthesis.
- Short WAV checks do not establish long-form or concurrency throughput.
