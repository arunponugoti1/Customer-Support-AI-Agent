"""One-time local OAuth helper — run on YOUR machine to authorize the connector for Gmail.

This is the single documented manual step (Gmail is a user resource and needs user consent).
It opens a browser, you grant access, and it prints the JSON to store in Secret Manager.

Prereqs:
  1. In the GCP project: enable the Gmail API; configure the OAuth consent screen (External,
     Testing) and add your Gmail as a test user; create an OAuth client ID of type
     "Desktop app" and download its JSON as client_secret.json.
  2. pip install google-auth-oauthlib
  3. python oauth_setup.py client_secret.json

It prints {client_id, client_secret, refresh_token}. Create the secret with that JSON:
  gcloud secrets create gmail-oauth --data-file=- --project <PROJECT>   # paste, then Ctrl-D/Z
(or `gcloud secrets versions add gmail-oauth --data-file=-` to rotate).

Note: while the consent screen is in "Testing", refresh tokens expire ~7 days; re-run this to
refresh, or publish the app for a long-lived token.
"""
import json
import sys

from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = ["https://www.googleapis.com/auth/gmail.modify",
          "https://www.googleapis.com/auth/gmail.send"]


def main():
    if len(sys.argv) != 2:
        print("usage: python oauth_setup.py <client_secret.json>"); sys.exit(1)
    flow = InstalledAppFlow.from_client_secrets_file(sys.argv[1], SCOPES)
    # access_type=offline + prompt=consent guarantees a refresh_token is returned.
    creds = flow.run_local_server(port=0, access_type="offline", prompt="consent")
    out = {
        "client_id": creds.client_id,
        "client_secret": creds.client_secret,
        "refresh_token": creds.refresh_token,
    }
    print("\n=== store THIS json in Secret Manager as 'gmail-oauth' ===\n")
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
