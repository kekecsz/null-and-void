"""Deploy the server to Google Cloud Run (specification 6.6). Values come from settings/cloud.yaml.

    .venv/Scripts/python deploy/cloud_run.py setup      # once: services, database, server identity
    .venv/Scripts/python deploy/cloud_run.py secrets    # the API key and the organiser password
    .venv/Scripts/python deploy/cloud_run.py deploy     # build and publish the current code
    .venv/Scripts/python deploy/cloud_run.py url        # print the address of the deployed game

``secrets`` asks for the organiser password without showing it, and hands it and the API key to
Secret Manager directly; neither is ever printed.
"""

import argparse
import getpass
import json
import shutil
import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from nv_ai.config import API_KEYS, KEY_NAMES, load_software_settings  # noqa: E402

CLOUD = yaml.safe_load((ROOT / "settings" / "cloud.yaml").read_text(encoding="utf-8"))
PROJECT, REGION = CLOUD["project"], CLOUD["region"]
ACCOUNT = f"{CLOUD['service_account']}@{PROJECT}.iam.gserviceaccount.com"
SERVICES = ["run", "cloudbuild", "artifactregistry", "firestore", "secretmanager"]
ORGANISER_SECRET = "NV_ORGANISER_PASSWORD"


def _key_name() -> str:
    return KEY_NAMES[load_software_settings().ai_provider]


def gcloud(*args: str, secret: bytes | None = None, check: bool = True, quiet: bool = False) -> subprocess.CompletedProcess:
    """Run gcloud in the project. ``secret`` goes to its standard input, never onto the command line."""
    program = shutil.which("gcloud")
    if program is None:
        sys.exit("gcloud was not found: install the Google Cloud CLI first")
    command = [program, *args, "--project", PROJECT]
    capture = quiet or secret is not None
    done = subprocess.run(command, input=secret, capture_output=capture, check=False, cwd=ROOT)
    if check and done.returncode != 0:
        if capture and done.stderr:
            print(done.stderr.decode("utf-8", "replace"), file=sys.stderr)
        sys.exit(f"gcloud failed: {' '.join(args[:3])}")
    return done


def exists(*args: str) -> bool:
    return gcloud(*args, check=False, quiet=True).returncode == 0


def setup(_: argparse.Namespace) -> None:
    print("Turning on the Google Cloud services (a minute or two)...")
    gcloud("services", "enable", *[f"{s}.googleapis.com" for s in SERVICES])
    if not exists("firestore", "databases", "describe"):
        print(f"Creating the Firestore database in {REGION} (its location cannot be changed later)...")
        gcloud("firestore", "databases", "create", f"--location={REGION}", "--type=firestore-native")
    if not exists("iam", "service-accounts", "describe", ACCOUNT):
        gcloud("iam", "service-accounts", "create", CLOUD["service_account"], "--display-name=Null and Void server")
    # The server may read and write the database; building from source needs the builder role.
    number = json.loads(gcloud("projects", "describe", PROJECT, "--format=json", quiet=True).stdout)["projectNumber"]
    for member, role in [(f"serviceAccount:{ACCOUNT}", "roles/datastore.user"),
                         (f"serviceAccount:{number}-compute@developer.gserviceaccount.com", "roles/run.builder")]:
        gcloud("projects", "add-iam-policy-binding", PROJECT, f"--member={member}", f"--role={role}", "--condition=None", quiet=True)
    print("Done. Next: deploy/cloud_run.py secrets")


def _api_key(name: str) -> str:
    if API_KEYS.exists():
        for line in API_KEYS.read_text(encoding="utf-8").splitlines():
            key, _, value = line.strip().partition("=")
            if key.strip() == name:
                return value.strip().strip('"').strip("'")
    return ""


def _store_secret(name: str, value: str) -> None:
    if not exists("secrets", "describe", name):
        gcloud("secrets", "create", name, "--replication-policy=user-managed", f"--locations={REGION}")
    gcloud("secrets", "versions", "add", name, "--data-file=-", secret=value.encode("utf-8"))
    gcloud("secrets", "add-iam-policy-binding", name, f"--member=serviceAccount:{ACCOUNT}",
           "--role=roles/secretmanager.secretAccessor", "--condition=None", quiet=True)
    print(f"Stored {name}.")


def secrets(_: argparse.Namespace) -> None:
    key_name = _key_name()
    key = _api_key(key_name)
    if not key:
        sys.exit(f"{key_name} is not in {API_KEYS}")
    _store_secret(key_name, key)
    password = getpass.getpass("Choose the organiser password (nothing is shown as you type): ")
    if password != getpass.getpass("The same again: "):
        sys.exit("The two passwords differ; nothing was changed for the organiser password.")
    if len(password) < 12:
        sys.exit("Please use at least 12 characters: this password protects your AI budget on the open internet.")
    _store_secret(ORGANISER_SECRET, password)
    print("Done. Next: deploy/cloud_run.py deploy")


def deploy(_: argparse.Namespace) -> None:
    key_name = _key_name()
    gcloud("run", "deploy", CLOUD["service"], "--source", ".", "--region", REGION, "--service-account", ACCOUNT,
           "--allow-unauthenticated", "--max-instances", str(CLOUD["max_instances"]), "--timeout", str(CLOUD["timeout_seconds"]),
           "--memory", str(CLOUD["memory"]), "--set-env-vars", "NV_STORAGE=firestore",
           "--set-secrets", f"{key_name}={key_name}:latest,{ORGANISER_SECRET}={ORGANISER_SECRET}:latest", "--quiet")
    url(_)


def url(_: argparse.Namespace) -> None:
    done = gcloud("run", "services", "describe", CLOUD["service"], "--region", REGION, "--format=json", quiet=True)
    print("The game is at:", json.loads(done.stdout)["status"]["url"])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("step", choices=["setup", "secrets", "deploy", "url"])
    args = parser.parse_args()
    {"setup": setup, "secrets": secrets, "deploy": deploy, "url": url}[args.step](args)


if __name__ == "__main__":
    main()
