"""一次性授权（在你自己的电脑运行）：取得只读 refresh token。
用法: GOOGLE_CLIENT_ID=... GOOGLE_CLIENT_SECRET=... python local_agent/get_google_token.py
"""
import os
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlencode, urlparse, parse_qs
import requests

ID, SECRET = os.environ["GOOGLE_CLIENT_ID"], os.environ["GOOGLE_CLIENT_SECRET"]
REDIRECT = "http://localhost:8765"
SCOPES = ("https://www.googleapis.com/auth/gmail.readonly "
          "https://www.googleapis.com/auth/calendar.readonly")
code = {}


class H(BaseHTTPRequestHandler):
    def do_GET(self):
        code["v"] = parse_qs(urlparse(self.path).query).get("code", [None])[0]
        self.send_response(200); self.end_headers()
        self.wfile.write("授权完成，可以关闭此页面。".encode())
    def log_message(self, *a): pass


url = "https://accounts.google.com/o/oauth2/v2/auth?" + urlencode({
    "client_id": ID, "redirect_uri": REDIRECT, "response_type": "code",
    "scope": SCOPES, "access_type": "offline", "prompt": "consent"})
webbrowser.open(url)
HTTPServer(("localhost", 8765), H).handle_request()
r = requests.post("https://oauth2.googleapis.com/token", data={
    "code": code["v"], "client_id": ID, "client_secret": SECRET,
    "redirect_uri": REDIRECT, "grant_type": "authorization_code"})
print("\nGOOGLE_REFRESH_TOKEN =", r.json()["refresh_token"])
print("把它存进 GitHub Secrets，不要分享给任何人。")
