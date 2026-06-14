#!/bin/bash
# Keeps the L2TP "School VPN" connected so vonbot can reach the MSSQL DB
# (192.168.36.250:1433). Run on login and every 60s via a LaunchAgent.
# Requires the VPN password/shared-secret to be saved in Keychain.

VPN_NAME="School VPN"

state="$(/usr/sbin/scutil --nc status "$VPN_NAME" 2>/dev/null | head -n 1)"

if [ "$state" != "Connected" ]; then
    echo "$(date '+%Y-%m-%d %H:%M:%S') VPN state='$state' -> starting"
    /usr/sbin/scutil --nc start "$VPN_NAME"
fi
