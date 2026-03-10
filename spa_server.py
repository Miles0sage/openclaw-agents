#!/usr/bin/env python3
"""
Simple HTTP server for Single Page Applications (SPA)
Serves index.html for all routes except static assets
"""
import http.server
import socketserver
import os
from pathlib import Path

class SPAHandler(http.server.SimpleHTTPRequestHandler):
    """Handler that serves index.html for all non-asset routes"""
    
    def end_headers(self):
        # Add CORS headers if needed
        self.send_header('Cache-Control', 'no-store, no-cache, must-revalidate')
        return super().end_headers()
    
    def _handle_request(self):
        """Common logic for GET and HEAD requests"""
        # Parse the path (remove query string and fragment)
        url_path = self.path.split('?')[0].split('#')[0]
        
        # If path is root or explicitly index.html, return True to serve normally
        if url_path == '/' or url_path == '/index.html':
            return True
        
        # Check if file exists in the assets directory
        full_path = self.translate_path(url_path)
        
        if os.path.exists(full_path) and os.path.isfile(full_path):
            return True
        
        # For all other routes, serve index.html (SPA routing)
        self.path = '/index.html'
        return True
    
    def do_GET(self):
        self._handle_request()
        return super().do_GET()
    
    def do_HEAD(self):
        self._handle_request()
        return super().do_HEAD()

if __name__ == '__main__':
    PORT = 5173
    DIRECTORY = "./dist/control-ui"
    
    # Change to the directory containing the UI
    os.chdir(DIRECTORY)
    
    # Allow reusing the address immediately (avoid "Address already in use" errors)
    socketserver.TCPServer.allow_reuse_address = True
    
    with socketserver.TCPServer(("", PORT), SPAHandler) as httpd:
        print(f"🦞 OpenClaw UI server running on http://0.0.0.0:{PORT}")
        print(f"   Serving: {DIRECTORY}")
        print(f"   SPA routing: All routes → index.html")
        httpd.serve_forever()
