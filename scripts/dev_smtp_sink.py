#!/usr/bin/env python3
"""
scripts/dev_smtp_sink.py

Lightweight standalone SMTP sink for environments where Mailpit cannot be downloaded
due to strict company PC policy. Listens on port 1025, accepts incoming emails, and saves
each as an RFC 822 .eml file into ./mail_outbox/ (which is git-ignored).

Usage:
    python scripts/dev_smtp_sink.py
"""
import asyncio
from datetime import datetime, timezone
import os
from pathlib import Path
import sys
import uuid

REPO_ROOT = Path(__file__).resolve().parent.parent
OUTBOX_DIR = REPO_ROOT / "mail_outbox"


class SmtpSinkProtocol(asyncio.Protocol):
    def __init__(self):
        self.transport = None
        self.state = "INIT"
        self.buffer = ""
        self.mail_from = ""
        self.rcpt_to = []
        self.data_lines = []

    def connection_made(self, transport):
        self.transport = transport
        self.transport.write(b"220 dev-smtp-sink GymPro AI Ready\r\n")

    def data_received(self, data):
        self.buffer += data.decode("utf-8", errors="replace")
        while "\r\n" in self.buffer or "\n" in self.buffer:
            if "\r\n" in self.buffer:
                line, self.buffer = self.buffer.split("\r\n", 1)
            else:
                line, self.buffer = self.buffer.split("\n", 1)
            self.handle_line(line)

    def handle_line(self, line: str):
        if self.state == "DATA":
            if line == ".":
                self.save_email()
                self.state = "COMMAND"
                self.data_lines = []
                self.transport.write(b"250 2.0.0 Ok: queued\r\n")
            else:
                # Handle dot-unstuffing
                if line.startswith(".."):
                    line = line[1:]
                self.data_lines.append(line)
            return

        cmd = line.strip()
        cmd_upper = cmd.upper()

        if cmd_upper.startswith("EHLO") or cmd_upper.startswith("HELO"):
            self.transport.write(b"250-dev-smtp-sink\r\n250-SIZE 10485760\r\n250 OK\r\n")
            self.state = "COMMAND"
        elif cmd_upper.startswith("MAIL FROM:"):
            self.mail_from = cmd[10:].strip()
            self.rcpt_to = []
            self.transport.write(b"250 2.1.0 Ok\r\n")
        elif cmd_upper.startswith("RCPT TO:"):
            self.rcpt_to.append(cmd[8:].strip())
            self.transport.write(b"250 2.1.5 Ok\r\n")
        elif cmd_upper == "DATA":
            self.state = "DATA"
            self.transport.write(b"354 End data with <CR><LF>.<CR><LF>\r\n")
        elif cmd_upper == "RSET":
            self.mail_from = ""
            self.rcpt_to = []
            self.data_lines = []
            self.state = "COMMAND"
            self.transport.write(b"250 2.0.0 Ok\r\n")
        elif cmd_upper == "NOOP":
            self.transport.write(b"250 2.0.0 Ok\r\n")
        elif cmd_upper == "QUIT":
            self.transport.write(b"221 2.0.0 Bye\r\n")
            self.transport.close()
        else:
            self.transport.write(b"502 5.5.2 Command not implemented\r\n")

    def save_email(self):
        OUTBOX_DIR.mkdir(parents=True, exist_ok=True)
        now_str = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        filename = f"email_{now_str}_{uuid.uuid4().hex[:8]}.eml"
        filepath = OUTBOX_DIR / filename

        content = "\r\n".join(self.data_lines)
        filepath.write_text(content, encoding="utf-8")
        print(f"[dev_smtp_sink] Saved email from {self.mail_from} to {self.rcpt_to} -> {filepath.name}")


async def main():
    host = "127.0.0.1"
    port = int(os.environ.get("SMTP_PORT", 1025))
    OUTBOX_DIR.mkdir(parents=True, exist_ok=True)

    loop = asyncio.get_running_loop()
    server = await loop.create_server(SmtpSinkProtocol, host, port)
    print(f"============================================================")
    print(f" GymPro AI Dev SMTP Sink running on {host}:{port}")
    print(f" Emails will be saved to: {OUTBOX_DIR}")
    print(f" Press Ctrl+C to stop")
    print(f"============================================================")

    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n[dev_smtp_sink] Stopped.")
        sys.exit(0)
