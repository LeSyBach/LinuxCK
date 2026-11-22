"""Write LinuxCK deployment files into a directory mounted at /setup."""

import argparse
import os
import re
import secrets
from pathlib import Path


TEMPLATES = Path(__file__).parent
DESTINATION = Path("/setup")


def write_if_missing(path, contents):
    try:
        with path.open("x", encoding="utf-8") as stream:
            stream.write(contents)
    except FileExistsError:
        print(f"Kept {path.name}")
    else:
        print(f"Created {path.name}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("image", help="The image tag or digest used for deployment")
    args = parser.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:/@-]*", args.image):
        parser.error("image must be a Docker image reference")
    if not DESTINATION.is_dir():
        parser.error("mount the deployment directory at /setup")

    role = os.environ["LINUXCK_SETUP_ROLE"]
    compose = [f"{role}.compose.yml", "beszel-agent.compose.yml"]
    beszel_env = [".env.beszel-agent"]
    env_text = (TEMPLATES / f"{role}.env.example").read_text(encoding="utf-8")
    env_text = env_text.replace("@IMAGE@", args.image)

    if role == "master":
        env_text = env_text.replace("@POSTGRES_PASSWORD@", secrets.token_hex(24))
        env_text = env_text.replace("@RABBITMQ_PASSWORD@", secrets.token_hex(24))
        compose.append("beszel-hub.compose.yml")
        beszel_env.append(".env.beszel-hub")

    os.umask(0o077)
    for name in compose:
        write_if_missing(DESTINATION / name, (TEMPLATES / name).read_text(encoding="utf-8"))
    write_if_missing(DESTINATION / f".env.{role}", env_text)

    beszel_text = (TEMPLATES / ".env.beszel.example").read_text(encoding="utf-8")
    for name in beszel_env:
        write_if_missing(DESTINATION / name, beszel_text)


if __name__ == "__main__":
    main()
