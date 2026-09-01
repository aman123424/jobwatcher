"""
lambda_handler.py
==================

The one new file needed to run the exact same FastAPI app (api.py) on
AWS Lambda instead of a normal always-on server.

WHY THIS FILE EXISTS AT ALL: uvicorn (what runs api.py locally, and
what would run it on a normal VM) is a real, persistent web server -
it opens a socket, listens for connections, and stays running. Lambda
doesn't work that way: AWS calls your code ONE TIME per incoming
request, hands it a plain JSON event describing that HTTP request, and
expects a plain JSON response back - there's no socket, no persistent
process, no uvicorn.

Mangum is the adapter that bridges this gap: it takes api.py's `app`
(a normal ASGI application - the same interface uvicorn talks to) and
wraps it in a function with the exact shape Lambda expects (event, in;
response, out). Nothing in api.py, main.py, fetchers.py, scoring.py,
job_dates.py, or companies.py needed to change for this - `app` is
used completely unmodified.

DEPLOYED VIA A LAMBDA FUNCTION URL, NOT API GATEWAY: API Gateway's
REST API type enforces a hard 29-second request timeout that can't be
raised - POST /refresh (a real ~10-60s live fetch across every
company) would get cut off mid-run. A Function URL talks to Lambda
directly, with no API Gateway in front of it, so it's bound only by
Lambda's own timeout (configured separately in the Lambda console,
set well above /refresh's real-world runtime - see the deployment
notes for the exact value used).

The name `handler` below is arbitrary but must match whatever's typed
into Lambda's own "Handler" configuration field
(lambda_handler.handler) - AWS looks up this exact module.attribute
path to know what to call for every incoming request.
"""

from mangum import Mangum

from api import app

handler = Mangum(app)
