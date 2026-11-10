"""Authentication and authorisation.

Nirantar handles the most sensitive category of personal data there is, so
the gate is a release requirement rather than a later milestone. Three rules
govern this file:

1. **We never mint credentials.** There is no Nirantar password, no Nirantar
   API key, no self-signed session token. A deploying organisation already
   has an identity provider -- a state health department's SSO, Keycloak,
   Auth0, Entra ID -- and we verify tokens it issued. Inventing our own
   auth would mean shipping a secret with no team to secure it.

2. **The gate verifies, it does not detect.** Middleware that waves through
   any request carrying a header is decorative. Tokens are checked for
   signature against the provider's published JWKS, plus issuer, audience
   and expiry, using a maintained library.

3. **It fails closed.** If the real verifier is not wired, gated routes
   reject every request and say exactly what to configure. There is no code
   path in which a missing configuration becomes an open door.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import jwt
from fastapi import Depends, HTTPException, Request, status
from jwt import PyJWKClient

from .config import Settings, get_settings

log = logging.getLogger("nirantar.security")

# Role required to read or act on person-level records.
ROLE_OPERATOR = "nirantar:operator"
# Role required to re-key the ledger or load real data.
ROLE_ADMIN = "nirantar:admin"

_jwks_client: PyJWKClient | None = None


def _jwks(settings: Settings) -> PyJWKClient:
    global _jwks_client
    if _jwks_client is None:
        uri = settings.jwks_uri()
        if not uri:
            raise RuntimeError("jwks_uri unavailable despite configured issuer")
        # PyJWKClient caches keys and refreshes on unknown kid.
        _jwks_client = PyJWKClient(uri, cache_keys=True, lifespan=600)
    return _jwks_client


@dataclass(frozen=True)
class Principal:
    subject: str
    roles: frozenset[str]
    issuer: str
    via: str  # "oidc" | "test-bypass"

    def has(self, role: str) -> bool:
        return role in self.roles or ROLE_ADMIN in self.roles


_UNCONFIGURED_DETAIL = (
    "This endpoint touches person-level health records and is therefore gated. "
    "No identity provider is configured, so the gate is rejecting every "
    "request (fail-closed by design). To enable it, set OIDC_ISSUER and "
    "OIDC_AUDIENCE to your organisation's identity provider and grant your "
    "operators the 'nirantar:operator' role. See docs/DEPLOY.md#authentication."
)


def _bearer(request: Request) -> str:
    header = request.headers.get("authorization", "")
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Bearer token required.",
            headers={"WWW-Authenticate": 'Bearer realm="nirantar"'},
        )
    return token.strip()


def _roles_from_claims(claims: dict, settings: Settings) -> frozenset[str]:
    raw = claims.get(settings.oidc_roles_claim)
    if raw is None:
        # Some providers nest roles; support the common Keycloak shape.
        raw = (claims.get("realm_access") or {}).get("roles")
    if isinstance(raw, str):
        return frozenset(part.strip() for part in raw.split() if part.strip())
    if isinstance(raw, (list, tuple)):
        return frozenset(str(item) for item in raw)
    return frozenset()


def authenticate(request: Request, settings: Settings) -> Principal:
    """Verify the caller, or raise. Never returns an unverified principal."""

    # Purpose-named, default-off, and refused outright when the process is
    # configured for real data (enforced again in Settings.validate).
    if settings.auth_test_bypass:
        if not settings.demo_mode:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Test bypass is not permitted outside demo mode.",
            )
        log.warning(
            "NIRANTAR_AUTH_TEST_BYPASS is enabled; gated routes are open to "
            "this process. Never set this in a deployment."
        )
        return Principal(
            subject="test-bypass",
            roles=frozenset({ROLE_OPERATOR, ROLE_ADMIN}),
            issuer="local-test",
            via="test-bypass",
        )

    if not settings.oidc_configured:
        # Fail closed. This is the branch that would otherwise become the
        # accidental open door.
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=_UNCONFIGURED_DETAIL,
        )

    token = _bearer(request)
    try:
        signing_key = _jwks(settings).get_signing_key_from_jwt(token)
        claims = jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256", "RS512", "ES256", "ES384"],
            audience=settings.oidc_audience,
            issuer=settings.oidc_issuer,
            options={
                "require": ["exp", "iat", "iss", "aud", "sub"],
                "verify_signature": True,
                "verify_exp": True,
                "verify_aud": True,
                "verify_iss": True,
            },
            leeway=30,
        )
    except HTTPException:
        raise
    except jwt.PyJWTError as exc:
        log.info("token rejected: %s", type(exc).__name__)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Token rejected: {type(exc).__name__}.",
            headers={"WWW-Authenticate": 'Bearer realm="nirantar", error="invalid_token"'},
        ) from exc
    except Exception as exc:  # JWKS fetch failures etc. -- still closed.
        log.warning("auth verification unavailable: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Unable to verify credentials against the identity provider.",
        ) from exc

    return Principal(
        subject=str(claims["sub"]),
        roles=_roles_from_claims(claims, settings),
        issuer=str(claims["iss"]),
        via="oidc",
    )


# --- FastAPI dependencies --------------------------------------------------


def require_operator(
    request: Request, settings: Settings = Depends(get_settings)
) -> Principal:
    """Gate for anything that reads or acts on person-level records."""
    principal = authenticate(request, settings)
    if not principal.has(ROLE_OPERATOR):
        # Authentication proves who is calling; this is the authorisation
        # half, which is a separate check on purpose.
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Role '{ROLE_OPERATOR}' required.",
        )
    return principal


def require_admin(
    request: Request, settings: Settings = Depends(get_settings)
) -> Principal:
    principal = authenticate(request, settings)
    if not principal.has(ROLE_ADMIN):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Role '{ROLE_ADMIN}' required.",
        )
    return principal


def demo_read(
    request: Request, settings: Settings = Depends(get_settings)
) -> Principal | None:
    """Gate for aggregate dashboard reads.

    In demo mode the dataset is entirely fictional and the whole point is
    that a judge, an NGO or a journalist can open it without an account, so
    anonymous access is the intended behaviour for generated data. The
    instant the process is configured for real records (``DEMO_MODE=false``)
    this becomes a full operator gate -- the same route, a different
    audience, decided by configuration rather than by hope.
    """
    if settings.demo_mode:
        return None
    return require_operator(request, settings)
