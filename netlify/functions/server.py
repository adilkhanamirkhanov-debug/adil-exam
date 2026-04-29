"""
Netlify serverless function entry point.

Wraps the Flask app with serverless-wsgi so it can run as
an AWS Lambda / Netlify Function.
"""
import sys
import os

# Add the function bundle root to the Python path so `app` can be imported.
# When Netlify deploys the function, `included_files` (app.py, templates/, static/)
# are placed alongside this file in the same bundle directory.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import serverless_wsgi  # noqa: E402  (installed via requirements.txt)
from app import app  # noqa: E402


def handler(event, context):
    return serverless_wsgi.handle_request(app, event, context)
