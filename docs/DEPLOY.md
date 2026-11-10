# Deploying Nirantar

Two situations, with very different requirements.

**A. A public demo on generated data.** What the hackathon needs. Anyone may
read it; every record is fictional. Straightforward.

**B. A real deployment holding real patient records.** Requires an identity
provider, and the process will refuse to start without one. Work through the
checklist in [`../SECURITY.md`](../SECURITY.md) before you load a single real
record.

---

## A. Public demo

### Docker (recommended)

```bash
docker compose up --build
# → http://127.0.0.1:8000
```

The container binds `0.0.0.0` internally so the platform's proxy can reach
it; the compose file publishes to `127.0.0.1:8000` only, and that mapping is
the real boundary. If a colleague needs access, forward the port over SSH
rather than widening the publish:

```bash
ssh -L 8000:127.0.0.1:8000 you@this-host
```

### Any container platform (Fly.io, Render, Cloud Run, App Runner, ECS)

The image is self-contained and serves both the API and the dashboard on one
port. Configure:

| Variable | Value |
|---|---|
| `HOST` | `0.0.0.0` — set by the platform, so its proxy can reach the app |
| `PORT` | whatever the platform injects |
| `DEMO_MODE` | `true` |
| `CORS_ORIGINS` | your public origin, e.g. `https://nirantar.example.org` |
| `DB_PATH` | a path on a persistent volume |
| `LEDGER_KEY_PATH` | a path on a persistent volume |
| `ANTHROPIC_API_KEY` | optional; set it as a secret, never as plain config |

**Attach a persistent volume** for `/app/var`. Without one, the ledger
signing key is regenerated on every deploy and the previously signed chain can
no longer be verified against the published key. The chain survives; your
ability to prove it does not.

TLS is terminated by the platform. Nirantar does not speak TLS itself and
should not be exposed directly on port 443.

### Verify the deploy

```bash
BASE=https://your-deployment.example.org

# 1. Liveness, and confirmation of which mode it came up in.
curl -s $BASE/api/health | jq
# expect: {"status":"ok","demo_mode":true,...}

# 2. The public surfaces must be anonymously readable — that is their job.
curl -s -o /dev/null -w '%{http_code}\n' $BASE/api/ledger/verify   # 200
curl -s -o /dev/null -w '%{http_code}\n' $BASE/api/calibration     # 200
curl -s -o /dev/null -w '%{http_code}\n' $BASE/                    # 200

# 3. The chain must verify.
curl -s $BASE/api/ledger/verify | jq '{valid, entries, key_id}'

# 4. Operator routes must be closed even in demo mode.
curl -s -o /dev/null -w '%{http_code}\n' $BASE/api/operator/whoami # 503 or 401
```

If step 4 returns 200, stop and fix it before sharing the link.

### Keeping demo costs bounded

A public demo with a live API key can be used to spend your money. Already
enforced:

- agent runs rate-limited to 25/hour per client, batch runs to 4/hour;
- bulk planning never calls a model at all;
- a global budget, `LLM_MAX_CALLS_PER_HOUR` (default 400), after which the
  agents fall back to their deterministic cores.

Note the limiter is **in-process, therefore per-replica**. It is a spend
guard, not a security control. For a widely-shared demo, either run a single
replica, put a rate limit at the edge, or simply leave `ANTHROPIC_API_KEY`
unset — the system is designed to run well without it.

---

## B. Real records

Do not skip this. With `DEMO_MODE=false` the process **exits at startup**
unless an identity provider is configured, and the error message names exactly
what is missing.

### Authentication

Nirantar mints no credentials. It verifies tokens issued by the OIDC provider
your organisation already runs — a state health department's SSO, Keycloak,
Auth0, Entra ID.

1. Register Nirantar as a client in your provider.
2. Create two roles, `nirantar:operator` (read and act on person-level
   records) and `nirantar:admin` (configuration).
3. Ensure the roles appear in the token claim named by `OIDC_ROLES_CLAIM`
   (default `roles`; Keycloak's `realm_access.roles` shape is also
   understood).
4. Configure:

```bash
DEMO_MODE=false
OIDC_ISSUER=https://sso.your-org.example/realms/health
OIDC_AUDIENCE=nirantar
# Only if your provider does not publish the standard discovery path:
# OIDC_JWKS_URL=https://sso.your-org.example/realms/health/protocol/openid-connect/certs
OIDC_ROLES_CLAIM=roles
CORS_ORIGINS=https://nirantar.your-org.example
```

5. Confirm `NIRANTAR_AUTH_TEST_BYPASS` is unset in every environment.

### Verify denial before loading data

The order matters. Deploy empty, prove the gate rejects anonymous callers,
*then* load records:

```bash
BASE=https://nirantar.your-org.example

curl -s -o /dev/null -w '%{http_code}\n' $BASE/api/overview   # expect 401
curl -si $BASE/api/overview | grep -i www-authenticate        # the gate's own header
curl -s -o /dev/null -w '%{http_code}\n' $BASE/api/worklist   # expect 401
```

A bare 403 is ambiguous — it can equally mean an undeployed route — so look
for the `WWW-Authenticate` header or your provider's redirect. **An anonymous
200 on person-level data means stop and fix.** The deployment is not done,
shareable, or reportable while that is true.

### Data integration

Replace `backend/nirantar/data/generator.py` with a client for your health
record system. The five agents consume the `World` interface and are unchanged
by the swap:

- `people` ← FHIR `Patient`
- `events` ← FHIR `Observation` (the abnormal results already in the NCD portal)
- `facilities` ← FHIR `Location` / `Organization` plus your stock system
- `ashas` ← FHIR `Practitioner`
- `outreach` ← your mobile medical unit roster
- `debts` ← derived from abnormal `Observation` resources

Care debts need **no new data collection**. That is the adoption argument.

### Before go-live

- [ ] Postgres instead of SQLite (see `Db` in `backend/nirantar/ledger.py` —
      the interface is narrow for exactly this reason).
- [ ] Ledger signing key in your secret manager, and backed up.
- [ ] Refit the attendance-model coefficients on your own data. The shipped
      values are published assumptions, not fitted parameters.
- [ ] **Native-speaker sign-off on every outreach script.** The code flags
      every generated script `requires_native_review`. Machine-written health
      messaging in somebody's mother tongue destroys trust in a programme.
- [ ] Real telephony and messaging providers wired to the generated
      artefacts.
- [ ] DPDP Act 2023 privacy review and whatever your state's health-data
      policy requires. The ledger is *designed* to be publishable; that is our
      design intent, not your legal clearance.
- [ ] Decide, explicitly and with clinicians, whether the Impact Ledger is
      published publicly or kept internal. It carries no identifying data by
      construction, but that is a decision for the programme, not for us.

---

## Render, step by step

`render.yaml` in the repository root is a Render Blueprint configured for the
**public demo**: generated data, anonymous aggregate reads, no model key.

### 1. Generate a ledger signing key

Render's free tier has an ephemeral filesystem and no persistent disks, so the
signing key must come from the secret store or it will be regenerated on every
deploy — at which point previously signed entries can no longer be verified
against the published public key.

```bash
python scripts/generate_ledger_key.py
```

That prints **one line of base64**, for `LEDGER_SIGNING_KEY_B64`. The single
line is deliberate. A multi-line PEM pasted into a dashboard secret field gets
its newlines flattened, and the service then dies at startup with an opaque
`Could not deserialize key data` — which is precisely how this project's first
deploy failed. `LEDGER_SIGNING_KEY_PEM` is still accepted and a flattened one
is now repaired, but prefer the single line.

Treat it as a credential: anyone holding it can forge ledger entries that
verify against the published public key. It never goes in a file in the
repository, and never anywhere it will be logged.

**You can also skip this entirely.** Leave the variable unset and the service
creates a key on boot and runs normally — you simply get a new key, and an
empty ledger, after each deploy. For a hackathon demo that is often fine.

### 2. Create the service

1. Sign in at <https://dashboard.render.com> (GitHub login works).
2. **New +** → **Blueprint**.
3. Choose this repository. Render reads `render.yaml` and proposes one web
   service named `nirantar`.
4. It will prompt for `LEDGER_SIGNING_KEY_B64` because that variable is marked
   `sync: false`. Paste the single line from step 1, or leave it blank.
5. **Apply**. The first build takes roughly 5–8 minutes: it builds the
   dashboard with Node, then the Python image.

Your URL will be `https://nirantar.onrender.com`, or with a suffix if that
name is taken.

### 3. Verify the deploy

```bash
BASE=https://nirantar.onrender.com

curl -s $BASE/api/health | jq
# expect demo_mode: true, llm_enabled: false

curl -s $BASE/api/ledger/verify | jq '{valid, entries, key_id}'
# the chain must verify

curl -s -o /dev/null -w 'landing: %{http_code}\n' $BASE/
curl -s -o /dev/null -w 'operator: %{http_code}\n' $BASE/api/operator/whoami
# landing 200 (public content must be reachable)
# operator 503 or 401 — never 200
```

If the operator route returns 200, stop and fix before sharing the link.

### Things to know about the free tier

- **It sleeps.** A free instance spins down after about 15 minutes idle, and
  the next request takes 30–60 seconds to wake it. Open the URL a minute
  before demoing, and warn a judge in your submission notes. A paid instance
  removes this.
- **The ledger resets on redeploy**, because there is no disk. The generated
  district is rebuilt identically from `DATA_SEED`, and the signing key stays
  stable through the secret, so verification still works — there are simply
  fewer entries. Uncomment the `disk:` block in `render.yaml` and move to a
  paid instance to persist the impact record.
- **Region** is set to Singapore, the closest Render region to the users this
  is built for.

### Enabling Claude on the live demo

Deliberately off. To turn it on, add `ANTHROPIC_API_KEY` as a secret in the
Render dashboard and redeploy. Before you do, read the spend-guard caveats
above: the rate limiter is per-replica and `X-Forwarded-For` is spoofable
behind Render's proxy, so a determined stranger can spend your tokens. For a
publicly linked demo, leaving it off is the better call — the dashboard states
plainly which mode it is in, and the deterministic path demonstrates
everything except the model's prose.
