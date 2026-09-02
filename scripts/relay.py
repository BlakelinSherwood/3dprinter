#!/usr/bin/env python3
"""Localhost -> Pi TCP relay for OctoPrint.

macOS Local Network privacy (TCC) blocks the studio's process tree from
reaching the Pi's LAN IP directly (errno 65). This forwarder runs from a
normal Terminal (which HAS Local Network permission) and bridges
127.0.0.1:5051 -> the Pi's OctoPrint at <pi-ip>:80, so OCTO_URL can point at
localhost and everything reaches the printer.

Usage:  python3 scripts/relay.py [pi_ip] [--listen 5051] [--to 80]
        default pi_ip = 10.0.0.112

If the Pi's IP changed (new DHCP lease), pass the new one:
        python3 scripts/relay.py 10.0.0.137
Find it with:  ping raspberrypi.local   (or check your router's client list)
"""
import argparse
import socket
import sys
import threading

DEFAULT_PI = "10.0.0.112"


def pipe(a, b):
    try:
        while True:
            data = a.recv(65536)
            if not data:
                break
            b.sendall(data)
    except OSError:
        pass
    finally:
        for s in (a, b):
            try:
                s.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass


def handle(client, pi_ip, pi_port):
    try:
        upstream = socket.create_connection((pi_ip, pi_port), timeout=10)
    except OSError as e:
        client.close()
        print(f"  upstream connect failed ({pi_ip}:{pi_port}): {e}", flush=True)
        return
    threading.Thread(target=pipe, args=(client, upstream), daemon=True).start()
    threading.Thread(target=pipe, args=(upstream, client), daemon=True).start()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("pi_ip", nargs="?", default=DEFAULT_PI)
    ap.add_argument("--listen", type=int, default=5051)
    ap.add_argument("--to", type=int, default=80)
    a = ap.parse_args()

    # fail fast if the Pi isn't reachable, so a dead relay doesn't look alive
    try:
        socket.create_connection((a.pi_ip, a.to), timeout=6).close()
    except OSError as e:
        print(f"Cannot reach the Pi at {a.pi_ip}:{a.to} - {e}\n"
              f"Is the Pi powered on? Its IP may have changed; try "
              f"'ping raspberrypi.local' or your router's device list, then "
              f"rerun: python3 scripts/relay.py <new-ip>", file=sys.stderr)
        sys.exit(1)

    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("127.0.0.1", a.listen))
    srv.listen(64)
    print(f"Relay up: 127.0.0.1:{a.listen} -> {a.pi_ip}:{a.to}  "
          f"(Ctrl-C to stop)", flush=True)
    try:
        while True:
            client, _ = srv.accept()
            handle(client, a.pi_ip, a.to)
    except KeyboardInterrupt:
        print("\nRelay stopped.")


if __name__ == "__main__":
    main()
