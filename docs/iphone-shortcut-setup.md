# bRAInZ — iPhone Shortcut Setup

Save security research directly from your iPhone's share sheet.

## Prerequisites

- bRAInZ running and accessible from your phone (see [Remote Access](#remote-access))
- Your API key (from `.env`)

---

## Shortcut 1: Save URL

Trigger from the iOS Share Sheet when viewing a webpage.

**Create in Shortcuts app:**

1. New Shortcut → Add Action
2. **Receive**: URLs from Share Sheet (enable "Receive input from: Share Sheet", type: URLs)
3. **Choose from Menu**:
   - Menu items: `appsec`, `reversing`, `netsec`, `ad-hacking`, `cloud-security`, `forensics`, `malware`, `crypto`, `osint`, `auto-classify`
4. **Get Contents of URL** (POST):
   - URL: `https://your-server:8000/api/ingest/url`
   - Method: `POST`
   - Headers:
     - `X-API-Key`: `[your-api-key]`
     - `Content-Type`: `application/json`
   - Request Body: JSON
     ```json
     {
       "url": "[Shortcut Input]",
       "category": "[Chosen Item]"
     }
     ```
     *(Set category value to empty string or omit the key if "auto-classify" was chosen)*
5. **Get Dictionary Value**: key `title` from result
6. **Show Notification**: "Saved: [Dictionary Value]"

**Name**: "Save to bRAInZ"

---

## Shortcut 2: Save Text Note

Trigger from Share Sheet when sharing selected text.

1. New Shortcut → Add Action
2. **Receive**: Text from Share Sheet
3. **Ask for Input**: "Title for this note" (type: Text)
4. **Get Contents of URL** (POST):
   - URL: `https://your-server:8000/api/ingest/text`
   - Method: `POST`
   - Headers: `X-API-Key`, `Content-Type: application/json`
   - Body JSON:
     ```json
     {
       "title": "[Provided Input]",
       "body": "[Shortcut Input]"
     }
     ```
5. **Show Notification**: "Note saved"

**Name**: "Save Note to bRAInZ"

---

## Shortcut 3: Quick Query

Standalone shortcut — ask your knowledge base a question.

1. New Shortcut → Add Action
2. **Ask for Input**: "Ask your security knowledge base" (type: Text)
3. **Get Contents of URL** (POST):
   - URL: `https://your-server:8000/api/query`
   - Method: `POST`
   - Headers: `X-API-Key`, `Content-Type: application/json`
   - Body JSON:
     ```json
     {
       "question": "[Provided Input]"
     }
     ```
4. **Get Dictionary Value**: key `answer` from result
5. **Show Result**: [Dictionary Value]

**Name**: "Ask bRAInZ"

---

## Remote Access

You need your bRAInZ instance accessible from your iPhone. Three options:

### Option 1: Tailscale (Recommended)

Simplest setup, works on any network, free for personal use.

```bash
# On your server (Linux)
curl -fsSL https://tailscale.com/install.sh | sh
sudo tailscale up

# Check your Tailscale IP
tailscale ip -4
```

Install Tailscale on your iPhone from the App Store. Sign in with the same account.

Use `http://100.x.x.x:8000` as your API URL in the shortcuts.

### Option 2: Cloudflare Tunnel

Zero-config HTTPS, no port forwarding.

```bash
# Install cloudflared
brew install cloudflare/cloudflare/cloudflared
# OR on Linux:
# curl -L https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64 -o /usr/local/bin/cloudflared

# One-time login
cloudflared tunnel login

# Create tunnel
cloudflared tunnel create brainz

# Run tunnel (add to systemd for persistence)
cloudflared tunnel run --url http://localhost:8000 brainz
```

This gives you a permanent `https://xxx.cfargotunnel.com` URL.

### Option 3: WireGuard

Full VPN approach — more setup, most control.

```bash
# Server
sudo apt install wireguard
wg genkey | tee /etc/wireguard/server_private.key | wg pubkey > /etc/wireguard/server_public.key

# Client (iPhone): install WireGuard app, scan QR code
# Full setup: https://www.wireguard.com/quickstart/
```

---

## Tips

- Store your API key in a Shortcuts dictionary or text variable so you update it in one place
- Test with the `/api/health` endpoint first to verify connectivity
- "auto-classify" as category means the LLM will decide — omit the category field entirely in the JSON
