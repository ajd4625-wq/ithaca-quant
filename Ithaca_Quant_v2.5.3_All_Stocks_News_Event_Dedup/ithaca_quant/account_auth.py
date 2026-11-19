"""Account-bound portfolio identity for Streamlit's verified OpenID Connect session.

Only use claims supplied by the trusted st.user object after is_logged_in;
never accept a subject supplied by an app text input.  Existing ledger code
stores a SHA-256 owner hash and cannot reveal this deterministic private key.
"""
from __future__ import annotations

import base64
import hashlib
import hmac


def account_access_code(subject: str, issuer: str, secret: str) -> str:
    """Stable, account-scoped internal ledger key; never displayed to users.

    Changing OIDC provider or identity can change the key. Not a password: the
    trusted login gate, not the derived key, enforces access authorization.
    Configure a stable server secret and keep it unchanged to retain access.
    """
    if not isinstance(subject, str) or not isinstance(issuer, str):
        raise ValueError('OIDC subject and issuer must be present.')
    subject, issuer = subject.strip(), issuer.strip()
    if not subject or not issuer or len(subject) > 2048 or len(issuer) > 2048:
        raise ValueError('A verified user subject and issuer are required.')
    if not isinstance(secret, str) or len(secret) < 32:
        raise ValueError('A stable server-side account identity secret (32+ characters) is required.')
    digest = hmac.new(secret.encode('utf-8'),
                      f'ithaca-oidc-owner-v1\0{issuer}\0{subject}'.encode('utf-8'),
                      hashlib.sha256).digest()
    return 'IQ-' + base64.urlsafe_b64encode(digest).decode('ascii').rstrip('=')[:32]


def claims_from_user(user) -> tuple[str, str]:
    """Reject missing stable provider identity; never key holdings by email."""
    if not bool(getattr(user, 'is_logged_in', False)):
        raise ValueError('Sign in before accessing your portfolio.')
    return user.get('sub'), user.get('iss')
