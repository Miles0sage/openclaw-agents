# Brick Builder Production Setup

## Status
✅ **Production configuration files created and ready for nginx deployment**

## What Was Done

### 1. Nginx Configuration
- **Location:** `/etc/nginx/sites-available/brick-builder`
- **Status:** Created and tested
- **Configuration details:**
  - Listens on port 8080
  - Serves frontend static files from `./services/brick-builder/frontend-dist/`
  - Proxies `/api/` requests to backend at `http://127.0.0.1:8001`
  - Proper cache headers for assets (30 days for JS/CSS/images, no-cache for HTML)
  - WebSocket upgrade support for API connections
  - Security: denies access to hidden files

### 2. Symlink to sites-enabled
- **Command:** `ln -sf /etc/nginx/sites-available/brick-builder /etc/nginx/sites-enabled/brick-builder`
- **Status:** ✅ Symlink created at `/etc/nginx/sites-enabled/brick-builder`

### 3. Frontend Distribution Directory
- **Location:** `./services/brick-builder/frontend-dist/`
- **Status:** ✅ Created and ready to receive built frontend files

### 4. Backend Service
- **Service:** `brick-builder`
- **Status:** ✅ Active and running on port 8001
- **Process:** Python3 Uvicorn server (PID 1839535)
- **Health check:** Responding at `/health`

## Next Steps (When Frontend is Ready)

1. **Copy built frontend** from remote PC to VPS:
   ```bash
   # From remote PC or via SCP:
   scp -r C:\Users\Miles\brick-builder\dist/* root@<your-vps-ip>:./services/brick-builder/frontend-dist/
   ```

2. **Install/reload nginx** on VPS:
   ```bash
   # Install if not already present
   apt-get update && apt-get install -y nginx

   # Test configuration
   nginx -t

   # Reload nginx to apply config
   systemctl reload nginx

   # Enable nginx to start on boot
   systemctl enable nginx
   ```

3. **Access the application:**
   - Frontend: `http://<your-vps-ip>:8080/`
   - API endpoints: `http://<your-vps-ip>:8080/api/...`
   - Backend direct: `http://<your-vps-ip>:8001/`
   - Health check: `http://<your-vps-ip>:8080/health`

## Configuration Details

### Nginx Config Highlights
- **Try files:** Falls back to `index.html` for SPA routing
- **Static asset caching:** 30-day expiry for JS, CSS, images, fonts
- **HTML caching:** No-cache to ensure fresh app shell
- **Proxy settings:**
  - Preserves original IP via X-Forwarded-For
  - 60s read timeout for API calls
  - Full WebSocket support
- **Security:** Hides dot-files from public access

## Current Environment
- **Nginx status:** Not yet installed (to be installed before deployment)
- **Backend status:** ✅ Running and healthy
- **VPS IP:** <your-vps-ip>
- **Port configuration:**
  - Backend: 8001 (private, only accessible internally)
  - Frontend: 8080 (public via nginx)

## Files Modified/Created
- `/etc/nginx/sites-available/brick-builder` — Main config
- `/etc/nginx/sites-enabled/brick-builder` — Symlink (created)
- `./services/brick-builder/frontend-dist/` — Directory created

## Testing
Once frontend files are in place and nginx is installed:
```bash
# Test nginx config syntax
nginx -t

# Should output:
# nginx: the configuration file /etc/nginx/nginx.conf syntax is ok
# nginx: configuration will be successful

# Reload nginx
systemctl reload nginx
```
