"""Shared pytest fixtures for the whole backend test suite.

`app.config` is fail-closed: a blank `JWT_SECRET` makes it raise `RuntimeError`
at import time, which is the correct production posture. But the test suite and
CI must be able to import the app without a real `.env`, so before any `app`
module loads we seed a throwaway secret.

The secret is deliberately fixed (not `secrets.token_hex`): tests that mint and
verify tokens need both sides to agree, and CI logs must stay diff-able. This
value never leaves the process and is not a production secret.
"""

import os

# Seed before `app` is imported by any test module. Conftest files are loaded by
# pytest ahead of test collection, so this is guaranteed to run first.
os.environ.setdefault("JWT_SECRET", "test-secret-do-not-use-in-production")
