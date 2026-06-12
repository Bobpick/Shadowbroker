#!/usr/bin/env python3
"""Live E2E: short-address lookup -> contact request -> Pete mailbox."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
import time
import urllib.error
import urllib.parse
import urllib.request

API = os.environ.get("SHADOWBROKER_API", "http://127.0.0.1:8000")
MARKER = os.environ.get("E2E_DM_MARKER", f"dm-short-addr-e2e-{int(time.time())}")
REPLY_MARKER = os.environ.get("E2E_DM_REPLY_MARKER", f"{MARKER}-reply")
PETE_HANDLE = os.environ.get("PETE_DM_SHORT_HANDLE", "").strip()
PETE_LOOKUP_PEER_URL = os.environ.get("PETE_DM_LOOKUP_PEER_URL", "").strip()
FRESH_BACKEND = os.environ.get("E2E_DM_FRESH_BACKEND", "1").strip().lower() not in {
    "0",
    "false",
    "no",
}
SSH_PETE = os.environ.get("PETE_SSH", "pete")
PETE_ONION = os.environ.get(
    "PETE_ONION",
    "nwbs4ur2usffb7lk3vyffhaqrijry544vmfjkk3qbrhvoh4v26fwxlid.onion:8000",
).strip()


def _docker_json(method: str, path: str, body: dict | None = None, *, admin_key: str = "", timeout_s: int = 30) -> dict:
    payload = ["docker", "exec", "shadowbroker-backend", "curl", "-s", "--max-time", str(timeout_s)]
    if admin_key:
        payload.extend(["-H", f"X-Admin-Key: {admin_key}"])
    if body is not None:
        payload.extend(["-H", "Content-Type: application/json", "-X", method.upper(), "-d", json.dumps(body)])
    else:
        payload.extend(["-X", method.upper()])
    payload.append(f"http://127.0.0.1:8000{path}")
    proc = subprocess.run(payload, capture_output=True, text=True, timeout=timeout_s + 15, check=False)
    raw = (proc.stdout or "").strip()
    if not raw:
        raise RuntimeError(proc.stderr.strip() or f"{method} {path} produced no response")
    parsed = json.loads(raw)
    if isinstance(parsed, dict) and parsed.get("detail") == "private_delivery_item_not_found" and method.upper() == "POST":
        return parsed
    return parsed if isinstance(parsed, dict) else {"ok": False, "detail": "invalid json response"}


def _json(method: str, path: str, body: dict | None = None, *, admin_key: str = "") -> dict:
    data = None
    headers = {"Content-Type": "application/json"}
    if admin_key:
        headers["X-Admin-Key"] = admin_key
    if body is not None:
        data = json.dumps(body, separators=(",", ":"), sort_keys=True).encode("utf-8")
    req = urllib.request.Request(f"{API}{path}", data=data, headers=headers, method=method.upper())
    try:
        with urllib.request.urlopen(req, timeout=300) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"{method} {path} -> {exc.code}: {detail}") from exc


def _docker_admin_key() -> str:
    proc = subprocess.run(
        ["docker", "exec", "shadowbroker-backend", "printenv", "ADMIN_KEY"],
        capture_output=True,
        text=True,
        check=True,
    )
    return proc.stdout.strip()


def _ssh_pete_admin_key() -> str:
    proc = subprocess.run(
        ["ssh", "-o", "BatchMode=yes", SSH_PETE, "docker exec shadowbroker-backend printenv ADMIN_KEY"],
        capture_output=True,
        text=True,
        check=True,
    )
    return proc.stdout.strip()


def _ensure_pete_invite(pete_admin: str) -> tuple[str, str]:
    if PETE_HANDLE:
        lookup = PETE_LOOKUP_PEER_URL or (
            f"http://{PETE_ONION}" if PETE_ONION else ""
        )
        return PETE_HANDLE, lookup.rstrip("/")
    proc = subprocess.run(
        [
            "ssh",
            "-o",
            "BatchMode=yes",
            SSH_PETE,
            f"curl -s -H 'X-Admin-Key: {pete_admin}' 'http://127.0.0.1:8000/api/wormhole/dm/invite?label=e2e-live'",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    invite = json.loads(proc.stdout)
    payload = dict(invite.get("invite", {}).get("payload", {}) or {})
    handle = str(payload.get("prekey_lookup_handle", "") or "").strip()
    lookup_peer_url = str(payload.get("lookup_peer_url", "") or "").strip().rstrip("/")
    if not handle:
        raise RuntimeError(f"could not mint Pete short handle: {invite}")
    return handle, lookup_peer_url


def _docker_python(code: str) -> dict:
    proc = subprocess.run(
        ["docker", "exec", "shadowbroker-backend", "python", "-c", code],
        capture_output=True,
        text=True,
        timeout=600,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or proc.stdout.strip() or "docker python failed")
    line = proc.stdout.strip().splitlines()[-1]
    return json.loads(line)


def _restart_local_backend() -> None:
    """Clear in-memory DM relay state (MESH_DM_PERSIST_SPOOL=false) before a repeat run."""
    proc = subprocess.run(
        [
            "docker",
            "compose",
            "-f",
            "docker-compose.yml",
            "-f",
            "docker-compose.build.yml",
            "restart",
            "backend",
        ],
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or proc.stdout.strip() or "backend restart failed")
    deadline = time.time() + 120
    while time.time() < deadline:
        probe = subprocess.run(
            [
                "docker",
                "exec",
                "shadowbroker-backend",
                "curl",
                "-sf",
                "--max-time",
                "5",
                "http://127.0.0.1:8000/api/health",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if probe.returncode == 0:
            print("local backend restarted and healthy")
            return
        time.sleep(3)
    raise RuntimeError("backend did not become healthy after restart")


def _wait_hidden_transport_ready(*, timeout_s: int = 120) -> dict:
    code = (
        "import json, time\n"
        "from services.mesh.mesh_private_dispatcher import _anonymous_dm_hidden_transport_enforced\n"
        f"deadline = time.time() + {int(timeout_s)}\n"
        "while time.time() < deadline:\n"
        "    if _anonymous_dm_hidden_transport_enforced():\n"
        "        print(json.dumps({'ok': True}))\n"
        "        break\n"
        "    time.sleep(2)\n"
        "else:\n"
        "    print(json.dumps({'ok': False, 'detail': 'hidden transport not ready'}))\n"
    )
    return _docker_python(code)


def _release_dm_outbox(admin_key: str, outbox_id: str, *, timeout_s: int = 180) -> dict:
    outbox_id = str(outbox_id or "").strip()
    if not outbox_id:
        return {"ok": False, "detail": "missing outbox_id"}
    _docker_json(
        "POST",
        f"/api/wormhole/private-delivery/{outbox_id}/action",
        {"action": "relay"},
        admin_key=admin_key,
    )
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        status = _docker_json("GET", "/api/wormhole/status", admin_key=admin_key)
        items = list((status.get("private_delivery") or {}).get("items") or [])
        item = next((entry for entry in items if str(entry.get("id", "")) == outbox_id), None)
        if item and str(item.get("release_state", "")) == "delivered":
            return {"ok": True, "item": item}
        time.sleep(3)
    return {"ok": False, "detail": "private release did not complete in time", "outbox_id": outbox_id}


def _drain_pete_request_mailbox() -> None:
    drain_code = textwrap.dedent(
        """
        import json, secrets, time, urllib.request
        from services.mesh.mesh_protocol import PROTOCOL_VERSION
        from services.mesh.mesh_wormhole_persona import get_dm_identity, sign_dm_wormhole_event

        def _poll_once():
            identity = get_dm_identity()
            agent_id = str(identity.get("node_id") or "")
            claims = [{"type": "requests", "token": "e2e-drain"}]
            signed = sign_dm_wormhole_event(
                event_type="dm_poll",
                payload={"mailbox_claims": claims, "agent_id": agent_id},
            )
            body = {
                "agent_id": agent_id,
                "mailbox_claims": claims,
                "timestamp": int(time.time()),
                "nonce": secrets.token_hex(8),
                "public_key": str(signed.get("public_key") or ""),
                "public_key_algo": str(signed.get("public_key_algo") or ""),
                "signature": str(signed.get("signature") or ""),
                "sequence": int(signed.get("sequence") or 0),
                "protocol_version": str(signed.get("protocol_version") or PROTOCOL_VERSION),
            }
            data = json.dumps(body, separators=(",", ":"), sort_keys=True).encode("utf-8")
            req = urllib.request.Request(
                "http://127.0.0.1:8000/api/mesh/dm/poll",
                data=data,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=60) as resp:
                return json.loads(resp.read().decode("utf-8"))

        drained = 0
        for _ in range(8):
            payload = _poll_once()
            count = int(payload.get("count", 0) or 0)
            drained += count
            if count <= 0 and not payload.get("has_more"):
                break
            time.sleep(1)
        print(json.dumps({"ok": True, "drained": drained}))
        """
    ).strip()
    result = _ssh_pete_python(drain_code)
    print(f"Pete request mailbox drain: {result.get('drained', 0)} message(s)")


def _warmup_tor() -> None:
    """Prime local Arti SOCKS before fleet lookups (cold Tor can exceed lookup budgets)."""
    if not PETE_ONION:
        return
    proc = subprocess.run(
        [
            "docker",
            "exec",
            "shadowbroker-backend",
            "curl",
            "-s",
            "-o",
            "/dev/null",
            "-w",
            "%{http_code}",
            "--max-time",
            "120",
            "--socks5-hostname",
            "127.0.0.1:9050",
            f"http://{PETE_ONION}/api/health",
        ],
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )
    code = (proc.stdout or "").strip()
    print(f"Tor warmup Pete health: {code or proc.stderr.strip() or 'failed'}")


def _ssh_pete_python(code: str) -> dict:
    # Pipe script stdin to Pete's running backend container — avoids Windows
    # docker-exec base64 bugs and SSH command-line length limits on long polls.
    proc = subprocess.run(
        [
            "ssh",
            "-o",
            "BatchMode=yes",
            SSH_PETE,
            "docker exec -i shadowbroker-backend python",
        ],
        input=code.encode("utf-8"),
        capture_output=True,
        timeout=300,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or proc.stdout.strip() or "pete python failed")
    lines = [line for line in proc.stdout.strip().splitlines() if line.strip()]
    if not lines:
        raise RuntimeError(proc.stderr.strip() or "pete python produced no output")
    return json.loads(lines[-1])


def main() -> int:
    if FRESH_BACKEND:
        print("== prep: restart local backend for clean in-memory DM relay ==")
        _restart_local_backend()

    print("== prep: drain stale Pete request mailbox ==")
    _drain_pete_request_mailbox()

    print("== warmup: prime Tor to Pete ==")
    _warmup_tor()

    print("== warmup: wait for anonymous hidden transport ==")
    hidden = _wait_hidden_transport_ready()
    print(json.dumps(hidden, indent=2))
    if not hidden.get("ok"):
        raise RuntimeError(f"hidden transport not ready: {hidden}")

    local_admin = _docker_admin_key()
    pete_admin = _ssh_pete_admin_key()
    handle, lookup_peer_url = _ensure_pete_invite(pete_admin)
    print(f"Pete short handle: {handle}")
    if lookup_peer_url:
        print(f"Pete lookup peer: {lookup_peer_url}")

    print("== step 1: fleet pubkey lookup from local ==")
    lookup_path = f"/api/mesh/dm/pubkey?lookup_token={handle}"
    if lookup_peer_url:
        lookup_path += f"&lookup_peer_url={urllib.parse.quote(lookup_peer_url, safe='')}"
    lookup = _json("GET", lookup_path)
    if not lookup.get("ok") or not lookup.get("agent_id") or not lookup.get("dh_pub_key"):
        print(json.dumps(lookup, indent=2))
        raise RuntimeError("pubkey fleet lookup failed")
    pete_id = str(lookup["agent_id"])
    pete_dh = str(lookup.get("dh_pub_key") or "")
    print(f"resolved Pete agent_id: {pete_id}")

    print("== step 2: send contact request from local ==")
    send_code = (
        "import json\n"
        "from services.openclaw_infonet import send_contact_request\n"
        f"result = send_contact_request(lookup_token={json.dumps(handle)}, note={json.dumps(MARKER)}, lookup_peer_url={json.dumps(lookup_peer_url)})\n"
        "print(json.dumps({"
        "'ok': bool(result.get('ok')), "
        "'send': result, "
        "'msg_id': result.get('msg_id',''), "
        "'sender_id': result.get('sender_id',''), "
        "'recipient_id': result.get('recipient_id','')"
        "}))\n"
    )
    send_result = _docker_python(send_code)
    print(json.dumps(send_result, indent=2))
    if not send_result.get("ok"):
        raise RuntimeError(f"local send failed: {send_result}")
    msg_id = str(send_result.get("msg_id", "") or "")

    print("== step 2b: approve relay release and wait for fleet push ==")
    outbox_id = str((send_result.get("send") or {}).get("outbox_id", "") or "")
    release = _release_dm_outbox(local_admin, outbox_id)
    print(json.dumps(release, indent=2))
    if not release.get("ok"):
        raise RuntimeError(f"private release failed: {release}")

    print("== step 3: wait for fleet replication, poll Pete relay ==")
    # Hit the running uvicorn process via localhost HTTP — dm_relay is in-memory
    # and is not visible to one-off `docker exec python` shells.
    poll_code = textwrap.dedent(
        f"""
        import json, secrets, time, urllib.error, urllib.request
        from services.mesh.mesh_protocol import PROTOCOL_VERSION
        from services.mesh.mesh_wormhole_persona import get_dm_identity, sign_dm_wormhole_event

        msg_id = {json.dumps(msg_id)}
        marker = {json.dumps(MARKER)}
        sender_id = {json.dumps(send_result.get('sender_id', ''))}

        def _mailbox_claims():
            return [{{"type": "requests", "token": "e2e-poll"}}]

        def _poll_once():
            identity = get_dm_identity()
            agent_id = str(identity.get("node_id") or "")
            claims = _mailbox_claims()
            signed = sign_dm_wormhole_event(
                event_type="dm_poll",
                payload={{"mailbox_claims": claims, "agent_id": agent_id}},
            )
            body = {{
                "agent_id": agent_id,
                "mailbox_claims": claims,
                "timestamp": int(time.time()),
                "nonce": secrets.token_hex(8),
                "public_key": str(signed.get("public_key") or ""),
                "public_key_algo": str(signed.get("public_key_algo") or ""),
                "signature": str(signed.get("signature") or ""),
                "sequence": int(signed.get("sequence") or 0),
                "protocol_version": str(signed.get("protocol_version") or PROTOCOL_VERSION),
            }}
            data = json.dumps(body, separators=(",", ":"), sort_keys=True).encode("utf-8")
            req = urllib.request.Request(
                "http://127.0.0.1:8000/api/mesh/dm/poll",
                data=data,
                headers={{"Content-Type": "application/json"}},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=120) as resp:
                return json.loads(resp.read().decode("utf-8"))

        hit = None
        for attempt in range(30):
            time.sleep(4)
            try:
                payload = _poll_once()
            except urllib.error.HTTPError as exc:
                detail = exc.read().decode("utf-8", errors="replace")
                if exc.code == 202:
                    continue
                print(json.dumps({{"ok": False, "detail": f"poll http {{exc.code}}: {{detail}}"}}))
                break
            except Exception as exc:
                print(json.dumps({{"ok": False, "detail": str(exc) or type(exc).__name__}}))
                break
            for message in list(payload.get("messages") or []):
                if str(message.get("msg_id", "")) == msg_id:
                    hit = message
                    break
                if marker in str(message.get("ciphertext", "")):
                    hit = message
                    break
            if hit:
                print(json.dumps({{"ok": True, "attempt": attempt, "msg_id": msg_id}}))
                break
        else:
            print(json.dumps({{"ok": False, "detail": "request not in Pete relay mailboxes"}}))
        """
    ).strip()
    poll = _ssh_pete_python(poll_code)
    print(json.dumps(poll, indent=2))
    if not poll.get("ok"):
        raise RuntimeError(f"Pete did not receive request: {poll}")

    print("== step 4: Pete bootstrap-decrypt contact offer ==")
    decrypt_code = textwrap.dedent(
        f"""
        import json, secrets, time, urllib.error, urllib.request
        from services.mesh.mesh_protocol import PROTOCOL_VERSION
        from services.mesh.mesh_wormhole_persona import get_dm_identity, sign_dm_wormhole_event
        from services.mesh.mesh_wormhole_prekey import bootstrap_decrypt_from_sender

        sender_id = {json.dumps(send_result.get('sender_id', ''))}
        msg_id = {json.dumps(msg_id)}

        identity = get_dm_identity()
        agent_id = str(identity.get("node_id") or "")
        claims = [{{"type": "requests", "token": "e2e-poll"}}]
        signed = sign_dm_wormhole_event(
            event_type="dm_poll",
            payload={{"mailbox_claims": claims, "agent_id": agent_id}},
        )
        body = {{
            "agent_id": agent_id,
            "mailbox_claims": claims,
            "timestamp": int(time.time()),
            "nonce": secrets.token_hex(8),
            "public_key": str(signed.get("public_key") or ""),
            "public_key_algo": str(signed.get("public_key_algo") or ""),
            "signature": str(signed.get("signature") or ""),
            "sequence": int(signed.get("sequence") or 0),
            "protocol_version": str(signed.get("protocol_version") or PROTOCOL_VERSION),
        }}
        data = json.dumps(body, separators=(",", ":"), sort_keys=True).encode("utf-8")
        req = urllib.request.Request(
            "http://127.0.0.1:8000/api/mesh/dm/poll",
            data=data,
            headers={{"Content-Type": "application/json"}},
            method="POST",
        )
        ciphertext = ""
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
            for message in list(payload.get("messages") or []):
                if str(message.get("msg_id", "")) == msg_id:
                    ciphertext = str(message.get("ciphertext", "") or "")
                    break
        except Exception as exc:
            print(json.dumps({{"ok": False, "detail": str(exc) or type(exc).__name__}}))
        elif not ciphertext:
            print(json.dumps({{"ok": False, "detail": "ciphertext missing on Pete"}}))
        else:
            dec = bootstrap_decrypt_from_sender(sender_id, ciphertext)
            print(json.dumps({{"ok": bool(dec.get("ok")), "plaintext": dec.get("result", ""), "detail": dec.get("detail", "")}}))
        """
    ).strip()
    decrypted = _ssh_pete_python(decrypt_code)
    print(json.dumps(decrypted, indent=2))
    if not decrypted.get("ok") or MARKER not in str(decrypted.get("plaintext", "")):
        raise RuntimeError(f"Pete could not decrypt contact offer: {decrypted}")

    local_sender_id = str(send_result.get("sender_id", "") or "")
    if not local_sender_id:
        raise RuntimeError("local sender_id missing from send result")

    print("== step 5: Pete accepts contact request ==")
    accept_code = textwrap.dedent(
        f"""
        import json, os
        os.environ.setdefault("SB_API_BASE", "http://127.0.0.1:8000")
        from services.openclaw_infonet import send_contact_accept
        result = send_contact_accept(peer_id={json.dumps(local_sender_id)})
        print(json.dumps({{
            "ok": bool(result.get("ok")),
            "msg_id": result.get("msg_id", ""),
            "shared_alias": result.get("shared_alias", ""),
            "detail": result.get("detail", ""),
        }}))
        """
    ).strip()
    accept_result = _ssh_pete_python(accept_code)
    print(json.dumps(accept_result, indent=2))
    if not accept_result.get("ok"):
        raise RuntimeError(f"Pete accept failed: {accept_result}")
    accept_msg_id = str(accept_result.get("msg_id", "") or "")

    print("== step 5b: release Pete accept to fleet relay ==")
    print(json.dumps(_ssh_pete_python(release_code), indent=2))

    print("== step 6: local polls and decrypts contact accept ==")
    local_accept_code = textwrap.dedent(
        f"""
        import json, secrets, time, urllib.error, urllib.request
        from services.mesh.mesh_protocol import PROTOCOL_VERSION
        from services.mesh.mesh_wormhole_dead_drop import parse_contact_consent
        from services.mesh.mesh_wormhole_persona import get_dm_identity, sign_dm_wormhole_event
        from services.mesh.mesh_wormhole_prekey import bootstrap_decrypt_from_sender

        sender_id = {json.dumps(local_sender_id)}
        accept_msg_id = {json.dumps(accept_msg_id)}
        pete_id = {json.dumps(pete_id)}

        identity = get_dm_identity()
        agent_id = str(identity.get("node_id") or "")
        claims = [{{"type": "requests", "token": "e2e-local-poll"}}]
        signed = sign_dm_wormhole_event(
            event_type="dm_poll",
            payload={{"mailbox_claims": claims, "agent_id": agent_id}},
        )
        body = {{
            "agent_id": agent_id,
            "mailbox_claims": claims,
            "timestamp": int(time.time()),
            "nonce": secrets.token_hex(8),
            "public_key": str(signed.get("public_key") or ""),
            "public_key_algo": str(signed.get("public_key_algo") or ""),
            "signature": str(signed.get("signature") or ""),
            "sequence": int(signed.get("sequence") or 0),
            "protocol_version": str(signed.get("protocol_version") or PROTOCOL_VERSION),
        }}
        data = json.dumps(body, separators=(",", ":"), sort_keys=True).encode("utf-8")

        hit = None
        for attempt in range(30):
            time.sleep(4)
            req = urllib.request.Request(
                "http://127.0.0.1:8000/api/mesh/dm/poll",
                data=data,
                headers={{"Content-Type": "application/json"}},
                method="POST",
            )
            try:
                with urllib.request.urlopen(req, timeout=120) as resp:
                    payload = json.loads(resp.read().decode("utf-8"))
            except Exception as exc:
                print(json.dumps({{"ok": False, "detail": str(exc) or type(exc).__name__}}))
                break
            for message in list(payload.get("messages") or []):
                if str(message.get("msg_id", "")) == accept_msg_id:
                    hit = message
                    break
                if str(message.get("sender_id", "")) == pete_id:
                    hit = message
                    break
            if hit:
                break
        if not hit:
            print(json.dumps({{"ok": False, "detail": "accept not in local requests mailbox"}}))
        else:
            ciphertext = str(hit.get("ciphertext", "") or "")
            dec = bootstrap_decrypt_from_sender(pete_id, ciphertext)
            consent = parse_contact_consent(str(dec.get("result", "") or ""))
            print(json.dumps({{
                "ok": bool(dec.get("ok") and consent and consent.get("kind") == "contact_accept"),
                "shared_alias": str((consent or {{}}).get("shared_alias", "") or ""),
                "detail": dec.get("detail", ""),
            }}))
        """
    ).strip()
    local_accept = _docker_python(local_accept_code)
    print(json.dumps(local_accept, indent=2))
    if not local_accept.get("ok") or not local_accept.get("shared_alias"):
        raise RuntimeError(f"local could not decrypt contact accept: {local_accept}")

    print("== step 7: local sends shared DM reply ==")
    shared_send_code = textwrap.dedent(
        f"""
        import json, os
        os.environ.setdefault("SB_API_BASE", "http://127.0.0.1:8000")
        from services.mesh.mesh_wormhole_dead_drop import derive_dead_drop_token_pair
        from services.openclaw_infonet import send_dm
        token_pair = derive_dead_drop_token_pair(
            peer_id={json.dumps(pete_id)},
            peer_dh_pub={json.dumps(pete_dh)},
        )
        if not token_pair.get("ok"):
            print(json.dumps(token_pair))
        else:
            result = send_dm(
                {json.dumps(pete_id)},
                {json.dumps(REPLY_MARKER)},
                delivery_class="shared",
                recipient_token=str(token_pair.get("current") or ""),
            )
            print(json.dumps({{
                "ok": bool(result.get("ok")),
                "msg_id": result.get("msg_id", ""),
                "detail": result.get("detail", ""),
            }}))
        """
    ).strip()
    shared_send = _docker_python(shared_send_code)
    print(json.dumps(shared_send, indent=2))
    if not shared_send.get("ok"):
        raise RuntimeError(f"local shared DM send failed: {shared_send}")
    shared_msg_id = str(shared_send.get("msg_id", "") or "")

    print("== step 7b: release local shared DM to fleet relay ==")
    print(json.dumps(_docker_python(release_code), indent=2))

    print("== step 8: Pete polls shared mailbox and decrypts reply ==")
    shared_poll_code = textwrap.dedent(
        f"""
        import json, secrets, time, urllib.error, urllib.request
        from services.mesh.mesh_protocol import PROTOCOL_VERSION
        from services.mesh.mesh_wormhole_dead_drop import derive_dead_drop_token_pair
        from services.mesh.mesh_wormhole_persona import get_dm_identity, sign_dm_wormhole_event
        sender_id = {json.dumps(local_sender_id)}
        shared_msg_id = {json.dumps(shared_msg_id)}
        marker = {json.dumps(REPLY_MARKER)}

        bundle = __import__(
            "services.mesh.mesh_wormhole_prekey",
            fromlist=["fetch_dm_prekey_bundle"],
        ).fetch_dm_prekey_bundle(agent_id=sender_id)
        sender_dh = str(bundle.get("dh_pub_key") or "")
        token_pair = derive_dead_drop_token_pair(peer_id=sender_id, peer_dh_pub=sender_dh)
        if not token_pair.get("ok"):
            print(json.dumps(token_pair))
            raise SystemExit(0)
        tokens = [str(token_pair.get("current") or "")]
        prev = str(token_pair.get("previous") or "")
        if prev and prev not in tokens:
            tokens.append(prev)

        identity = get_dm_identity()
        agent_id = str(identity.get("node_id") or "")
        claims = [{{"type": "shared", "token": token}} for token in tokens if token]

        hit = None
        for attempt in range(30):
            time.sleep(4)
            signed = sign_dm_wormhole_event(
                event_type="dm_poll",
                payload={{"mailbox_claims": claims, "agent_id": agent_id}},
            )
            body = {{
                "agent_id": agent_id,
                "mailbox_claims": claims,
                "timestamp": int(time.time()),
                "nonce": secrets.token_hex(8),
                "public_key": str(signed.get("public_key") or ""),
                "public_key_algo": str(signed.get("public_key_algo") or ""),
                "signature": str(signed.get("signature") or ""),
                "sequence": int(signed.get("sequence") or 0),
                "protocol_version": str(signed.get("protocol_version") or PROTOCOL_VERSION),
            }}
            data = json.dumps(body, separators=(",", ":"), sort_keys=True).encode("utf-8")
            req = urllib.request.Request(
                "http://127.0.0.1:8000/api/mesh/dm/poll",
                data=data,
                headers={{"Content-Type": "application/json"}},
                method="POST",
            )
            try:
                with urllib.request.urlopen(req, timeout=120) as resp:
                    payload = json.loads(resp.read().decode("utf-8"))
            except Exception as exc:
                print(json.dumps({{"ok": False, "detail": str(exc) or type(exc).__name__}}))
                break
            for message in list(payload.get("messages") or []):
                if str(message.get("msg_id", "")) == shared_msg_id:
                    hit = message
                    break
            if hit:
                break

        if not hit:
            print(json.dumps({{"ok": False, "detail": "shared reply not in Pete mailbox"}}))
        else:
            ciphertext = str(hit.get("ciphertext", "") or "")
            dec = __import__("main", fromlist=["decrypt_wormhole_dm_envelope"]).decrypt_wormhole_dm_envelope(
                peer_id=sender_id,
                ciphertext=ciphertext,
                payload_format=str(hit.get("format", "") or "mls1"),
                session_welcome=str(hit.get("session_welcome", "") or ""),
            )
            plaintext = str(dec.get("plaintext", "") or "")
            print(json.dumps({{
                "ok": bool(dec.get("ok") and marker in plaintext),
                "plaintext": plaintext,
                "detail": dec.get("detail", ""),
            }}))
        """
    ).strip()
    shared_decrypt = _ssh_pete_python(shared_poll_code)
    print(json.dumps(shared_decrypt, indent=2))
    if not shared_decrypt.get("ok") or REPLY_MARKER not in str(shared_decrypt.get("plaintext", "")):
        raise RuntimeError(f"Pete could not decrypt shared DM: {shared_decrypt}")

    print("== E2E PASS: invite -> accept -> private shared DM ==")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"E2E FAIL: {exc}", file=sys.stderr)
        raise
