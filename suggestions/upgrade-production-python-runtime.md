# Upgrade the production Python runtime

Observed friction: the shared host currently exposes only cPanel Python 3.9.23
for this application, while Python 3.9 is end-of-life. The system `python3` is
older still and is not a viable Passenger runtime.

Impact: security and compatibility fixes increasingly require dependency
versions that no longer support the deployed interpreter.

Next step: when Inleed/cPanel offers a supported Python release, create the new
application virtualenv, then deploy with
`ARXIV_PYTHON_VERSION=<major.minor>`. The deploy preflight verifies the selected
interpreter, and `passenger_wsgi.py` no longer injects a 3.9-specific package
path.
