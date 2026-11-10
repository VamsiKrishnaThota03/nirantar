# Security

Nirantar handles the most sensitive category of personal data there is. The
gate is a release requirement, not a later milestone. This document states
what is enforced, what is deliberately open, and what you must configure
before pointing this at a single real patient record.

## Reporting a vulnerability

Open a GitHub issue for anything non-sensitive. For anything exploitable,
contact the maintainers privately rather than filing a public issue, and
please allow a reasonable window before disclosure.

---

## The two audiences, decided in code

The split lives in one place, `backend/nirantar/api/routes.py`, so it can be
audited:

| Surface | Access | Why |
|---|---|---|
| `/api/ledger/*`, `/api/calibration`, `/api/health` | **Anonymous, always** | A tamper-evident impact record that only we can read is worth nothing. The ledger carries no identifying data by construction. |
| Aggregate district views, person-level demo views, the field-app queue, agent runs, the trial | Anonymous **only while `DEMO_MODE=true`** | Every record is generated and fictional, and the point of a public demo is that a judge or an NGO can open it without an account. The field queue in particular carries names and villages, so it is behind the same gate and becomes operator-only the moment the process holds real records. |
| `/api/operator/*` | **Always gated** | Touches configuration and real data paths. |
| Everything above, when `DEMO_MODE=false` | **Always gated** | The same routes, a different audience, decided by configuration rather than by hope. |

## What is enforced

**Loopback by default.** `HOST` defaults to `127.0.0.1` in
`backend/nirantar/config.py`. A wildcard bind is never the default. A
container platform that terminates TLS in front of the app sets `HOST`
explicitly in its own deployment config; `docker-compose.yml` publishes to
`127.0.0.1:8000` only. If you need the service from another machine, use an
SSH local port-forward rather than widening the bind.

**Fail-closed on real data.** `Settings.validate()` raises and the process
exits if `DEMO_MODE=false` and no identity provider is configured. There is no
code path in which a missing configuration becomes an open door. Asserted by
`tests/test_security.py::test_real_data_mode_refuses_to_start_without_auth`.

**The gate verifies; it does not detect.** Middleware that waves through any
request carrying a header is decorative. Bearer tokens are checked for
signature against the provider's published JWKS, plus issuer, audience and
expiry, using PyJWT. Unverifiable tokens get 401; an unreachable provider gets
503. Never 200.

**No invented authentication.** There is no Nirantar password, no Nirantar API
key, and no self-signed session token. A secret we mint ourselves is invented
auth even with cryptographically correct verification, because it has no team
to secure and maintain it. Nirantar verifies tokens issued by whichever OIDC
provider the deploying organisation already runs.

**Authorisation is a separate check.** Authentication proves who is calling.
`ROLE_OPERATOR` gates person-level data; `ROLE_ADMIN` gates configuration.

**The test bypass defaults to deny.** `NIRANTAR_AUTH_TEST_BYPASS` is
purpose-named — never keyed off an ambient variable like `ENV` or `NODE_ENV` —
defaults to off, logs loudly when on, and the process refuses to start if it
is set while `DEMO_MODE=false`.

**No CORS wildcard.** `CORS_ORIGINS` defaults to loopback dev origins. A
wildcard plus credentials is how a dashboard becomes readable by any page the
user happens to visit.

**The signing key is owner-only from the outset.** Created with
`O_CREAT|O_EXCL` and mode `0600` rather than chmod-ed after the bytes are
already on disk.

**No credentials in delivered files.** `docker-compose.yml` references
`${ANTHROPIC_API_KEY:-}` and friends; nothing in this repository contains a
credential value.

## What is deliberately open, and the limits of it

While `DEMO_MODE=true`, anonymous callers can read the generated district and
trigger agent runs. This is intentional: the demo is useless if a judge needs
an account. The containment is:

- every record is fictional, generated from a seed;
- agent runs and batch runs are rate-limited per client (25/hour and 4/hour);
- bulk planning **never** calls a language model, and there is a global
  model-call budget (`LLM_MAX_CALLS_PER_HOUR`, default 400);
- no endpoint accepts person-level data *in*.

The rate limiter is in-process and therefore per-replica. **It is a spend
guard, not a security control**, and should not be relied on as one.

## Before you point this at real records

Everything below is a human step we cannot do for you.

- [ ] Register Nirantar as a confidential client in your identity provider.
- [ ] Set `OIDC_ISSUER` and `OIDC_AUDIENCE` (and `OIDC_JWKS_URL` if your
      provider does not publish the standard discovery path).
- [ ] Grant your operators the `nirantar:operator` role and your
      administrators `nirantar:admin`, in the claim named by
      `OIDC_ROLES_CLAIM` (default `roles`; Keycloak's `realm_access.roles`
      shape is also understood).
- [ ] Set `DEMO_MODE=false`. Confirm the process starts; if it exits, the
      error says exactly what is missing.
- [ ] Confirm `NIRANTAR_AUTH_TEST_BYPASS` is unset everywhere.
- [ ] Set `CORS_ORIGINS` to your real dashboard origin.
- [ ] Terminate TLS in front of the app. Nirantar does not speak TLS itself.
- [ ] **Verify denial before loading data.** Deploy empty, then fetch a
      person-level endpoint as an anonymous client and require a 401/403 that
      is identifiably the gate's. Only after you have observed that denial,
      load records. An anonymous 200 on patient data means stop and fix.
- [ ] Move the ledger signing key into your secret manager and back it up.
      Losing it does not invalidate past entries, but you cannot sign new
      ones consistently without it.
- [ ] Replace SQLite with Postgres for anything beyond a single block. The
      `Db` wrapper in `ledger.py` is deliberately narrow to make this a
      drop-in change.
- [ ] Have a native speaker sign off every outreach script before a single
      call is placed. Machine-written health messaging in somebody's mother
      tongue destroys trust in a programme; the code flags every generated
      script `requires_native_review` for exactly this reason.
- [ ] Complete a privacy review under the DPDP Act 2023 and your state's
      health-data policy. Nirantar's ledger is designed to be publishable,
      but **that is our design intent, not your legal clearance.**

## The service worker

`frontend/public/sw.js` caches the application shell — HTML, JS, CSS — so the
field app opens with no signal. It is registered in production builds only,
so a stale cache can never shadow the dev server.

**It never caches `/api` responses.** Two reasons, and both are deliberate:
health data should not be left lying in a browser HTTP cache, and a stale care
obligation is more dangerous than a missing one. The field view instead keeps
its own explicit snapshot in local storage and *tells the user* when it is
showing cached data — a visible decision rather than an invisible one.

The field app's offline evidence queue also lives in local storage, which
means a completed visit is briefly held on the handset. That is a considered
trade: a health worker who cannot record a visit without a signal will stop
recording visits. The queue holds only an obligation reference and an evidence
type, never a clinical record, and it is flushed and cleared as soon as a
connection returns.

## Privacy design notes

- The public ledger stores a keyed hash of the internal record id, not the id.
  The key is derived from the signing key and never leaves the process.
- Ledger payloads are restricted to an allowlist of non-identifying fields,
  enforced in `ledger.py` rather than left to callers.
  `tests/test_ledger.py::test_ledger_carries_no_identifying_data` tries to
  log a name, a phone number and a village, and asserts all three were
  dropped.
- Outreach scripts **never name the diagnosis**. Handsets in this setting are
  frequently shared and often belong to a husband or son rather than to the
  woman being called, so the call says only that a check-up follow-up is
  pending. This is enforced in the script builder, not left to a prompt.
- Nirantar stores no telephone numbers. A real deployment reads them from the
  health record system at send time and should not copy them here.
