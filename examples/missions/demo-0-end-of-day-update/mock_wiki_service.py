#!/usr/bin/env python3
"""Mock Wiki Service API for testing Demo 0."""

import json
from http.server import HTTPServer, BaseHTTPRequestHandler

# Mock wiki data
wiki_data = {
    "ai-safety": {
        "pages": [
            {"title": "Scalable Oversight for Advanced AI Systems", "content": "Research on scalable oversight..."},
            {"title": "Constitutional AI: Safety through Natural Language", "content": "Constitutional AI approach..."},
            {"title": "Mechanistic Interpretability of LLMs", "content": "Understanding how LLMs work..."},
            {"title": "AI Alignment Research Overview", "content": "Overview of alignment research..."},
            {"title": "Safety Considerations for Large Language Models", "content": "Safety considerations..."}
        ]
    },
    "governance": {
        "pages": [
            {"title": "EU AI Act Implementation Guidelines", "content": "EU AI Act details..."},
            {"title": "NIST AI Risk Management Framework v2.0", "content": "NIST framework..."}
        ]
    }
}


class WikiHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        """Handle GET requests."""
        # Parse path: /topics/<topic>/pages
        parts = self.path.split('/')

        if len(parts) >= 4 and parts[1] == 'topics' and parts[3] == 'pages':
            topic = parts[2]

            # Check authorization
            auth_header = self.headers.get('Authorization')
            if not auth_header or not auth_header.startswith('Bearer '):
                self.send_response(401)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({"error": "No access token"}).encode())
                return

            # In production, would validate token with Mission Authority
            # For mock, just check format
            access_token = auth_header[7:]
            if not access_token.startswith('access-'):
                self.send_response(403)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({"error": "Invalid access token"}).encode())
                return

            # Get wiki data
            if topic not in wiki_data:
                self.send_response(404)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({"error": f"Topic '{topic}' not found"}).encode())
                return

            response = wiki_data[topic]

            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps(response).encode())

        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        """Custom log format."""
        print(f"[Wiki Service] {format % args}")


def main():
    port = 8002
    server = HTTPServer(('localhost', port), WikiHandler)
    print(f"Mock Wiki Service running on http://localhost:{port}")
    print(f"Press Ctrl+C to stop")
    print()
    print("Available endpoints:")
    print("  GET /topics/<topic>/pages - Read wiki pages (requires Bearer token)")
    print()
    print("Available topics:")
    for topic in wiki_data.keys():
        print(f"  - {topic} ({len(wiki_data[topic]['pages'])} pages)")
    print()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down...")
        server.shutdown()


if __name__ == "__main__":
    main()
