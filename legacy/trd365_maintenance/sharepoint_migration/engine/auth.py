"""
Per-tenant app-only authentication for Microsoft Graph.

Cross-tenant migration needs TWO independent tokens — one from the source
tenant's app registration, one from the dest tenant's — because each tenant only
trusts its own app registration. Each uses the OAuth2 client-credentials flow
(app-only, no user) via MSAL, with the `.default` scope so the app's
admin-consented application permissions apply.

Supports either a client secret or a certificate (thumbprint + private key).
Tokens are cached in-process and refreshed automatically before expiry by MSAL.
"""

import time

try:
    import msal
except ImportError:  # pragma: no cover
    raise SystemExit("msal is required. Install with:  pip install -r requirements.txt")

GRAPH_SCOPE = ["https://graph.microsoft.com/.default"]


class TenantAuth:
    """Acquires + caches an app-only Graph token for ONE tenant."""

    def __init__(self, name, tenant_id, client_id, client_secret=None, certificate=None):
        self.name = name
        authority = f"https://login.microsoftonline.com/{tenant_id}"
        if certificate and certificate.get("thumbprint") and certificate.get("private_key_path"):
            with open(certificate["private_key_path"]) as fh:
                private_key = fh.read()
            cred = {"thumbprint": certificate["thumbprint"], "private_key": private_key}
        elif client_secret:
            cred = client_secret
        else:
            raise ValueError(f"[{name}] provide either client_secret or a certificate")
        self._app = msal.ConfidentialClientApplication(
            client_id, authority=authority, client_credential=cred)
        self._token = None
        self._exp = 0

    def token(self):
        # refresh ~2 min before expiry
        if self._token and time.time() < self._exp - 120:
            return self._token
        result = self._app.acquire_token_for_client(scopes=GRAPH_SCOPE)
        if "access_token" not in result:
            raise RuntimeError(
                f"[{self.name}] token request failed: "
                f"{result.get('error')}: {result.get('error_description', '')[:300]}")
        self._token = result["access_token"]
        self._exp = time.time() + int(result.get("expires_in", 3600))
        return self._token

    @classmethod
    def from_config(cls, name, cfg):
        return cls(name, cfg["tenant_id"], cfg["client_id"],
                   client_secret=cfg.get("client_secret"),
                   certificate=cfg.get("certificate"))
