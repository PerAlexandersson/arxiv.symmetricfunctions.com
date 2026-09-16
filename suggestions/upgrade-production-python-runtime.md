# Upgrade the production Python runtime

Status: resolved on 2026-09-16. Python 3.11.16 and all pinned dependencies are
installed, cPanel reports 3.11/started, and all observed Passenger workers now
use the 3.11 virtualenv after the hosting-side configuration took effect.

Observed friction: the application previously used cPanel Python 3.9.23 after
that release reached end-of-life. The system `python3` is older still and is
not a viable Passenger runtime.

Impact: security and compatibility fixes increasingly require dependency
versions that no longer support the deployed interpreter.

Resolution: the pinned application dependencies were installed in the cPanel
3.11 virtualenv, the deploy default was updated to 3.11, and worker command
lines plus `VIRTUAL_ENV` now confirm the live runtime. Future changes should use
`ARXIV_PYTHON_VERSION=<major.minor>`; the deploy preflight verifies the selected
interpreter, and `passenger_wsgi.py` does not inject a version-specific package
path.
