# Lessons from selfhost and manual SaaS release

- Operator-configured HTTPS origin is authoritative; never derive a trusted
  public URL from an unvalidated Host/X-Forwarded header. Backend metadata, UI,
  gateway Origin checks and Swagger must use the same configuration.
- Keep owner management, owner legacy key and customer personal keys separate.
  Customer prefix must not inherit the local-owner bypass used by the desktop UI.
- Reserve quota with one database transaction before inference; only finalize
  once. Failures/restart refund reserved characters without changing completed
  usage. Changing plans does not reset monthly usage.
- Optional native addons need compiler tools and their managed Python on the
  persistent volume. Testing one Vietnamese model is not testing Japanese/Chinese.
- Source tests, real model inference in an isolated DB, and live browser/admin
  reachability establish different facts. Record each and avoid activating paid
  plans or creating hidden production users merely to test the release.
