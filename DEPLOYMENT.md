# Deployment

How `vonbot` is served at **https://vonbot.pucsr.edu.kh** from a **Mac Mini that has no fixed public IP**.

## Architecture

```
visitor browser
      |  https
      v
Cloudflare edge (anycast, hides the Mac's IP, terminates TLS, enforces WAF allowlist)
      |  outbound tunnel (cloudflared dials OUT — no inbound ports, no public IP needed)
      v
Mac Mini ── Streamlit app (127.0.0.1:8501)
      |  L2TP "School VPN" (split tunnel)
      v
MSSQL DB  192.168.36.250:1433   (New_PUCDB, SQL Server 2008 R2)
```

- **No public IP / no port forwarding.** `cloudflared` makes an outbound connection to Cloudflare; visitors are routed back down it. The Mac's real IP is never exposed.
- **DNS** is a *proxied CNAME* `vonbot.pucsr.edu.kh -> <tunnel-id>.cfargotunnel.com` (not an A record to an IP).
- **The DB is only reachable over the L2TP VPN.** The app is the bridge — it holds the VPN + `sa` connection. Split tunnel: only DB routes go through the VPN, general traffic uses the local ISP.

## Prerequisites

- macOS with [Homebrew](https://brew.sh)
- `brew install cloudflared`
- [`uv`](https://docs.astral.sh/uv/) for the Python env
- The `pucsr.edu.kh` zone on Cloudflare, with account access
- The L2TP **"School VPN"** configured in System Settings with its password/shared-secret **saved in Keychain** (so it can reconnect headlessly)

## 1. App environment

```bash
cd /Users/jeffreystark/Development/key/vonbot
uv sync                      # builds .venv with Python 3.13 + deps
cp .env.example .env         # then fill in real values (see below)
```

`.env` (gitignored — never commit) needs:

```
LEGACY_DB_HOST=192.168.36.250   # internal IP over the VPN (NOT the public 96.9.90.64)
LEGACY_DB_PORT=1433             # standard MSSQL port (NOT 1500)
LEGACY_DB_USER=sa
LEGACY_DB_PASSWORD=...
LEGACY_DB_NAME=New_PUCDB
ADMIN_USERNAME=...
ADMIN_PASSWORD=...
```

Smoke-test the DB (VPN must be up):

```bash
.venv/bin/python -c "from dotenv import load_dotenv; load_dotenv(); \
from database.connection import get_db_connection; \
c=get_db_connection(); cur=c.cursor(); cur.execute('SELECT 1'); print('OK', cur.fetchone()[0])"
```

## 2. Cloudflare Tunnel

```bash
cloudflared tunnel login                         # browser -> pick pucsr.edu.kh zone
cloudflared tunnel create vonbot                 # prints <tunnel-id>, writes secret JSON
cloudflared tunnel route dns vonbot vonbot.pucsr.edu.kh   # creates the proxied CNAME
```

If `route dns` errors that a record already exists, delete the old `vonbot` record in
Cloudflare DNS first, then re-run.

Then create `~/.cloudflared/config.yml` from
[`deploy/cloudflared-config.example.yml`](deploy/cloudflared-config.example.yml),
substituting the real `<tunnel-id>`.

## 3. Auto-start services (launchd)

Three user **LaunchAgents** keep everything running and restart it on drop. Templates are in
[`deploy/launchagents/`](deploy/launchagents/) — they assume user `jeffreystark` and this repo
path; edit if either differs.

```bash
cp deploy/launchagents/com.vonbot.*.plist ~/Library/LaunchAgents/

UID_NUM=$(id -u)
for svc in com.vonbot.streamlit com.vonbot.cloudflared com.vonbot.vpn-keepalive; do
  launchctl bootstrap gui/$UID_NUM ~/Library/LaunchAgents/$svc.plist
  launchctl enable    gui/$UID_NUM/$svc
done
launchctl list | grep vonbot     # all three should be listed
```

| Agent | Does |
|-------|------|
| `com.vonbot.streamlit`     | runs `.venv/bin/streamlit run app.py` on `127.0.0.1:8501` (KeepAlive) |
| `com.vonbot.cloudflared`   | runs `cloudflared tunnel run vonbot` (KeepAlive) |
| `com.vonbot.vpn-keepalive` | runs `scripts/vpn-keepalive.sh` at login + every 60s; reconnects "School VPN" if down |

## 4. Edge security — WAF IP allowlist

The app is otherwise public to the whole internet, gated only by its own admin login. Because the
25-year-old DB's `sa` password cannot be changed, restrict who can even reach the app at Cloudflare's
edge (a Mac-side firewall can't do this — all tunnel traffic arrives as `127.0.0.1`).

Cloudflare dashboard → **Security → WAF → Custom rules → Create rule**, action **Block**:

```
(http.host eq "vonbot.pucsr.edu.kh" and not ip.src in {96.9.90.0/24})
```

`96.9.90.0/24` is the campus/ISP block (school egress + the Mac's dynamic IP). Everyone else gets a
Cloudflare 1020 page before reaching the app. Widen the CIDR if the ISP ever assigns an IP outside
`96.9.90.x`.

## 5. Reboot / power-failure behavior

- `pmset autorestart 1` + `sleep 0` are set, so the Mac powers back on and never sleeps.
- **FileVault is ON** — after an *unexpected* power loss the Mac halts at the disk-unlock screen and
  needs the password typed **once**, by hand. This is by design and the only manual step.
- Once unlocked, the user session starts (unlock = login) and all three agents fire. The VPN takes
  ~60–90s to re-handshake, so DB-backed pages lag ~1–2 min after boot; the app itself loads immediately.

## Operations

```bash
# restart the app after code changes
launchctl kickstart -k gui/$(id -u)/com.vonbot.streamlit

# tail logs
tail -f logs/streamlit.err.log logs/cloudflared.err.log logs/vpn-keepalive.log

# check public health
curl -s -o /dev/null -w "%{http_code}\n" https://vonbot.pucsr.edu.kh/_stcore/health

# VPN status
scutil --nc status "School VPN" | head -1
```

## Not in this repo (lives only on the Mac, by design)

- `.env` — secrets (gitignored)
- `~/.cloudflared/<tunnel-id>.json` — tunnel credentials (secret)
- Installed copies of the plists under `~/Library/LaunchAgents/`
