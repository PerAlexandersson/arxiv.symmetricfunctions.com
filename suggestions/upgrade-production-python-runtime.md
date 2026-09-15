# Upgrade the production Python runtime

Status: Python 3.11.16 and all pinned dependencies are installed, and the
deployment configuration points to 3.11. The cPanel selector still reports
3.9 until its UI update/start action completes.

Observed friction: the application previously used cPanel Python 3.9.23 after
that release reached end-of-life. The system `python3` is older still and is
not a viable Passenger runtime.

Impact: security and compatibility fixes increasingly require dependency
versions that no longer support the deployed interpreter.

Resolution in progress: the pinned application dependencies were installed in
the cPanel 3.11 virtualenv and the deploy default was updated to 3.11. Complete
the selector change in cPanel, then verify that Passenger worker command lines
use the 3.11 virtualenv. Future runtime changes should use
`ARXIV_PYTHON_VERSION=<major.minor>`; the deploy preflight verifies the selected
interpreter, and `passenger_wsgi.py` does not inject a version-specific package
path.
