#!/usr/bin/env python3
"""
Generate RS256 key pair and random TOKEN_HMAC_SECRET and write into .env.
Multi-line PEM keys are stored on one line with \n escapes.
"""
import os
import re
import secrets
from pathlib import Path
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import serialization

REPO_ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = REPO_ROOT / ".env"
ENV_EXAMPLE = REPO_ROOT / ".env.example"


def generate_rs256_keys():
    private_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
    )
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("utf-8")

    public_pem = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("utf-8")

    return private_pem, public_pem


def escape_pem(pem: str) -> str:
    cleaned = pem.strip().replace("\r\n", "\n")
    return cleaned.replace("\n", "\\n")


def main():
    private_pem, public_pem = generate_rs256_keys()
    token_hmac_secret = secrets.token_hex(32)

    escaped_private = escape_pem(private_pem)
    escaped_public = escape_pem(public_pem)

    if not ENV_FILE.exists():
        if ENV_EXAMPLE.exists():
            content = ENV_EXAMPLE.read_text(encoding="utf-8")
        else:
            content = ""
    else:
        content = ENV_FILE.read_text(encoding="utf-8")

    # Replace or append JWT_PRIVATE_KEY
    if re.search(r"^JWT_PRIVATE_KEY=.*$", content, flags=re.MULTILINE):
        content = re.sub(
            r"^JWT_PRIVATE_KEY=.*$",
            f'JWT_PRIVATE_KEY="{escaped_private}"',
            content,
            flags=re.MULTILINE,
        )
    else:
        content += f'\nJWT_PRIVATE_KEY="{escaped_private}"'

    # Replace or append JWT_PUBLIC_KEY
    if re.search(r"^JWT_PUBLIC_KEY=.*$", content, flags=re.MULTILINE):
        content = re.sub(
            r"^JWT_PUBLIC_KEY=.*$",
            f'JWT_PUBLIC_KEY="{escaped_public}"',
            content,
            flags=re.MULTILINE,
        )
    else:
        content += f'\nJWT_PUBLIC_KEY="{escaped_public}"'

    # Replace or append TOKEN_HMAC_SECRET
    if re.search(r"^TOKEN_HMAC_SECRET=.*$", content, flags=re.MULTILINE):
        content = re.sub(
            r"^TOKEN_HMAC_SECRET=.*$",
            f"TOKEN_HMAC_SECRET={token_hmac_secret}",
            content,
            flags=re.MULTILINE,
        )
    else:
        content += f"\nTOKEN_HMAC_SECRET={token_hmac_secret}"

    ENV_FILE.write_text(content.strip() + "\n", encoding="utf-8")
    print(f"Generated RS256 key pair and TOKEN_HMAC_SECRET in {ENV_FILE}")


if __name__ == "__main__":
    main()
