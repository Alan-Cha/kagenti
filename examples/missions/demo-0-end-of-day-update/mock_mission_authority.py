#!/usr/bin/env python3
"""Mock Mission Authority API for testing Demo 0."""

import json
import sys
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from http.server import HTTPServer, BaseHTTPRequestHandler

# File-based storage for persistence
STORAGE_DIR = Path.home() / ".claude" / "mock_mission_authority"
STORAGE_DIR.mkdir(parents=True, exist_ok=True)
MISSIONS_FILE = STORAGE_DIR / "missions.json"
TOKENS_FILE = STORAGE_DIR / "tokens.json"

def load_data():
    """Load missions and tokens from files."""
    missions = {}
    tokens = {}
    if MISSIONS_FILE.exists():
        missions = json.loads(MISSIONS_FILE.read_text())
    if TOKENS_FILE.exists():
        tokens = json.loads(TOKENS_FILE.read_text())
    return missions, tokens

def save_data(missions, tokens):
    """Save missions and tokens to files."""
    # Ensure directory exists (in case it was deleted)
    STORAGE_DIR.mkdir(parents=True, exist_ok=True)
    MISSIONS_FILE.write_text(json.dumps(missions, indent=2))
    TOKENS_FILE.write_text(json.dumps(tokens, indent=2))


class MissionAuthorityHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        """Handle POST requests."""
        missions, tokens = load_data()

        content_length = int(self.headers['Content-Length'])
        body = self.rfile.read(content_length)
        data = json.loads(body)

        if self.path == '/missions':
            # Create mission
            mission_id = f"M-{datetime.now().strftime('%Y%m%d')}-{str(uuid.uuid4())[:3]}"
            mission = {
                "mission_id": mission_id,
                "mission_text": data["mission_text"],
                "agent_id": data["agent_id"],
                "scope": data["scope"],
                "duration_hours": data["duration_hours"],
                "status": "pending",
                "created_at": datetime.now().isoformat(),
                "expires_at": (datetime.now() + timedelta(hours=data["duration_hours"])).isoformat()
            }
            missions[mission_id] = mission
            save_data(missions, tokens)

            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps(mission).encode())

        elif self.path == '/token-exchange':
            # Exchange mission token for access token
            mission_token = data["subject_token"]

            if mission_token not in tokens:
                self.send_response(403)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({"error": "Invalid mission token"}).encode())
                return

            mission_id = tokens[mission_token]
            mission = missions[mission_id]

            if mission["status"] != "active":
                self.send_response(403)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({"error": f"Mission status is {mission['status']}"}).encode())
                return

            # Generate access token
            access_token = f"access-{uuid.uuid4()}"
            scope = data.get("scope", "wiki_read")

            response = {
                "access_token": access_token,
                "token_type": "Bearer",
                "expires_in": 14400,  # 4 hours
                "scope": scope,
                "mission_id": mission_id
            }

            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps(response).encode())
            save_data(missions, tokens)

        else:
            self.send_response(404)
            self.end_headers()

    def do_GET(self):
        """Handle GET requests."""
        missions, tokens = load_data()

        if self.path.startswith('/missions/'):
            mission_id = self.path.split('/')[-1]

            if mission_id not in missions:
                self.send_response(404)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({"error": "Mission not found"}).encode())
                return

            mission = missions[mission_id]

            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps(mission).encode())

        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        """Custom log format."""
        print(f"[Mission Authority] {format % args}")


def approve_mission(mission_id: str):
    """Approve a mission (simulates user approval)."""
    missions, tokens = load_data()

    if mission_id not in missions:
        print(f"❌ Mission {mission_id} not found")
        return

    mission = missions[mission_id]

    if mission["status"] != "pending":
        print(f"❌ Mission {mission_id} is already {mission['status']}")
        return

    # Update mission
    mission["status"] = "active"
    mission["approver_id"] = "alice@example.com"
    mission["approved_at"] = datetime.now().isoformat()

    # Generate mission token
    mission_token = f"mission-token-{uuid.uuid4()}"
    tokens[mission_token] = mission_id

    # Save to persistent storage
    save_data(missions, tokens)

    # Save token to file (so skill can access it)
    token_file = Path.home() / ".claude" / "missions" / f"{mission_id}.token"
    token_file.parent.mkdir(parents=True, exist_ok=True)
    token_file.write_text(mission_token)

    print(f"✓ Mission {mission_id} approved")
    print(f"  Approver: alice@example.com")
    print(f"  Status: active")
    print(f"  Token saved to: {token_file}")


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "approve":
        if len(sys.argv) < 3:
            print("Usage: python mock_mission_authority.py approve <mission_id>")
            sys.exit(1)
        approve_mission(sys.argv[2])
        return

    # Start HTTP server
    port = 8001
    server = HTTPServer(('localhost', port), MissionAuthorityHandler)
    print(f"Mock Mission Authority running on http://localhost:{port}")
    print(f"Press Ctrl+C to stop")
    print()
    print("Available endpoints:")
    print("  POST /missions - Create mission")
    print("  GET  /missions/<id> - Get mission status")
    print("  POST /token-exchange - Exchange mission token for access token")
    print()
    print("To approve missions:")
    print("  python mock_mission_authority.py approve <mission_id>")
    print()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down...")
        server.shutdown()


if __name__ == "__main__":
    main()
