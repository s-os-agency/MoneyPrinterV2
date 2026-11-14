#!/usr/bin/env python3
"""Create one capped worker key and return it only as RSA-OAEP ciphertext."""

import base64
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from classes.OpenRouter import OpenRouterClient, OpenRouterError  # noqa: E402


def main():
    name = os.environ.get("WORKER_KEY_NAME", "")
    if not re.fullmatch(r"MoneyPrinterV2-text-worker-[A-Za-z0-9_-]{1,60}", name):
        raise ValueError("Choose an explicit MoneyPrinterV2 worker key name.")
    public = base64.b64decode(os.environ.get("DELIVERY_PUBLIC_KEY_B64", ""), validate=True)
    client = OpenRouterClient()
    out = ROOT / "key-delivery"
    out.mkdir(mode=0o700, exist_ok=True)
    with tempfile.TemporaryDirectory() as temporary:
        public_path = Path(temporary) / "public.pem"
        public_path.write_bytes(public)
        # Validate the delivery destination before creating a credential.
        public_info = subprocess.run([
            "openssl", "rsa", "-pubin", "-in", str(public_path), "-text", "-noout",
        ], check=True, capture_output=True).stdout.decode("ascii", errors="replace")
        bits = re.search(r"Public-Key: \((\d+) bit\)", public_info)
        if not bits or int(bits[1]) < 4096:
            raise ValueError("Use a delivery RSA public key of at least4096bits before creating a credential.")
        seen = set()
        for offset in range(0, 10000, 100):
            keys = client._request(f"/keys?include_disabled=true&offset={offset}").get("data")
            if not isinstance(keys, list):
                raise ValueError("Could not read existing key metadata; no creation attempted.")
            if any(key.get("name") == name for key in keys):
                raise ValueError("This named key already exists; recover its delivery artifact instead of creating a duplicate.")
            hashes = {key.get("hash") for key in keys}
            if keys and hashes <= seen:
                raise ValueError("Key pagination did not advance; no creation attempted.")
            seen.update(hashes)
            if len(keys) < 100:
                break
        else:
            raise ValueError("Key metadata was incomplete; no creation attempted.")
        result = client._request("/keys", {
            "name": name, "limit": 50, "limit_reset": "monthly",
            "include_byok_in_limit": True,
        })
        key = result.get("key")
        data = result.get("data", {})
        if not isinstance(key, str) or not key.startswith("sk-or-"):
            raise ValueError("Creation response lacked a worker credential; inspect account metadata before another attempt.")
        # The only artifact containing the credential is encrypted for the owner's
        # local delivery private key, which never enters this repository/runner.
        envelope = json.dumps({"key": key, "hash": data.get("hash"), "name": name,
                               "limit": data.get("limit"), "limit_reset": data.get("limit_reset")}).encode()
        ciphertext = subprocess.run([
            "openssl", "pkeyutl", "-encrypt", "-pubin", "-inkey", str(public_path),
            "-pkeyopt", "rsa_padding_mode:oaep", "-pkeyopt", "rsa_oaep_md:sha256",
        ], input=envelope, check=True, capture_output=True).stdout
        (out / "worker-key.rsa").write_bytes(ciphertext)
        metadata = {"name": name, "hash": data.get("hash"),
                    "limit": data.get("limit"), "limit_reset": data.get("limit_reset"),
                    "delivery": "RSA-OAEP-SHA256 ciphertext only"}
        (out / "metadata.json").write_text(json.dumps(metadata, indent=2) + "\n")
        if data.get("limit") != 50 or data.get("limit_reset") != "monthly":
            raise ValueError("Created key budget differs from the requested cap; do not activate it.")
        client.key = key
        status = client._request("/key").get("data", {})
        print(json.dumps({"worker_key_created": True, "worker_key_authorized": True,
                          "limit": status.get("limit"), "limit_reset": status.get("limit_reset"),
                          "encrypted_delivery_ready": True}))


if __name__ == "__main__":
    try:
        main()
    except (OpenRouterError, ValueError) as error:
        print(str(error))
        raise SystemExit(1)
    except Exception:
        print("Key setup stopped. Check named-key metadata and any encrypted artifact before another creation attempt.")
        raise SystemExit(1)
