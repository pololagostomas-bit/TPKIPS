"""Poll a public GitHub branch and deploy only its owner-merged PR commits.

Run on the trusted server, not from an incoming branch or a PR workflow.
The fixed Compose configuration is supplied by the server administrator.
"""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import time
from urllib.parse import quote
from urllib.request import Request, urlopen


def github(repository, path):
    request = Request(
        f"https://api.github.com/repos/{repository}/{path}",
        headers={"Accept": "application/vnd.github+json", "User-Agent": "triton-home-deployer"},
    )
    with urlopen(request, timeout=30) as response:
        return json.load(response)


def approved_merge(pr, repository, branch, sha):
    return (
        pr.get("state") == "closed"
        and bool(pr.get("merged_at"))
        and pr.get("merge_commit_sha") == sha
        and pr.get("base", {}).get("ref") == branch
        and pr.get("base", {}).get("repo", {}).get("full_name") == repository
        and (pr.get("merged_by") or {}).get("login") == repository.split("/")[0]
    )


def run(*args, env=None):
    return subprocess.run(args, check=True, text=True, env=env, timeout=900)


def save_state(path, state):
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def deploy(args):
    state_path = args.state_dir / "state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    candidate = github(args.repository, f"commits/{quote(args.base, safe='')}")["sha"]
    if candidate == state["sha"]:
        return "unchanged"
    if state.get("blocked_sha"):
        return "blocked: revisar el fallo anterior antes de cualquier despliegue"
    if not re.fullmatch(r"[0-9a-f]{40}", candidate):
        raise ValueError("SHA no valido")
    associated = github(args.repository, f"commits/{candidate}/pulls?per_page=100")
    authorized = any(
        approved_merge(github(args.repository, f"pulls/{pr['number']}"),
                       args.repository, args.base, candidate)
        for pr in associated
    )
    if not authorized:
        return "ignored: el commit no es un PR fusionado por el propietario"

    checkout = args.state_dir / "source"
    if not checkout.exists():
        run("git", "clone", "--no-checkout", "--single-branch", "--branch", args.base,
            f"https://github.com/{args.repository}.git", str(checkout))
    run("git", "-C", str(checkout), "fetch", "origin", args.base)
    run("git", "-C", str(checkout), "merge-base", "--is-ancestor", state["sha"], candidate)
    release = args.state_dir / "releases" / candidate
    if not release.exists():
        release.parent.mkdir(parents=True, exist_ok=True)
        run("git", "-C", str(checkout), "worktree", "add", "--detach", str(release), candidate)

    # Fixed, locally reviewed Compose prevents incoming branches from adding host mounts.
    compose = ["docker", "compose", "--env-file", str(args.env_file),
               "--project-directory", str(release / "infrastructure"),
               "-f", str(args.compose_file)]
    environment = dict(os.environ, WMS_IMAGE_TAG=candidate[:12])
    run(*compose, "config", "--quiet", env=environment)
    run(*compose, "build", "app", env=environment)
    run(*compose, "exec", "-T", "backup", "python", "-m", "backend.maintenance", "backup", env=environment)
    # Mark in-flight before touching services. A crash must not silently retry migrations.
    state["blocked_sha"] = candidate
    save_state(state_path, state)
    try:
        run(*compose, "up", "-d", "--no-build", "--wait", "--wait-timeout", "120", "app", "backup", env=environment)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
        run(*compose, "stop", "app", "backup", env=environment)
        raise RuntimeError("Nueva version detenida. Revisar salud y restaurar copia si procede; no se borro ningun volumen.")
    save_state(state_path, {"sha": candidate, "image_tag": candidate[:12]})
    return f"deployed: {candidate}"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--base", default="main")
    parser.add_argument("--state-dir", required=True, type=Path)
    parser.add_argument("--env-file", required=True, type=Path)
    parser.add_argument("--compose-file", required=True, type=Path)
    parser.add_argument("--initialize-sha", help="Record the already running version; never deploys")
    parser.add_argument("--watch", action="store_true")
    args = parser.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", args.repository):
        parser.error("Repositorio no valido")
    for key in ("state_dir", "env_file", "compose_file"):
        setattr(args, key, getattr(args, key).resolve())
    if not args.env_file.is_file() or not args.compose_file.is_file():
        parser.error("Falta configuracion local")
    args.state_dir.mkdir(parents=True, exist_ok=True)
    import fcntl
    with (args.state_dir / "deploy.lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if args.initialize_sha:
            if not re.fullmatch(r"[0-9a-f]{40}", args.initialize_sha):
                parser.error("SHA inicial no valido")
            with (args.state_dir / "state.json").open("x", encoding="utf-8") as output:
                json.dump({"sha": args.initialize_sha, "image_tag": "local"}, output)
            print("Estado inicial registrado; no se desplegaron cambios.")
            return
        while True:
            try:
                result = deploy(args)
                if result != "unchanged":
                    print(result, flush=True)
            except Exception as error:
                if not args.watch:
                    raise
                print(f"No se aplicaron cambios: {error}", flush=True)
            if not args.watch:
                break
            time.sleep(300)


if __name__ == "__main__":
    main()
