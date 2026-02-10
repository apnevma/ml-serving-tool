import os
import requests
import shutil


GITHUB_REPO = os.getenv("GITHUB_REPO")
GITHUB_BRANCH = os.getenv("GITHUB_BRANCH", "main")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")

MODELS_ROOT = "models"
MODELS_PATH= os.getenv("MODELS_PATH")    # path inside container

if not GITHUB_REPO:
    raise RuntimeError("GITHUB_REPO is not set")

HEADERS = {
    "Accept": "application/vnd.github+json"
}

if GITHUB_TOKEN:
    HEADERS["Authorization"] = f"token {GITHUB_TOKEN}"

TIMEOUT = 15


def list_repo_root():
    url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{MODELS_ROOT}"
    params = {"ref": GITHUB_BRANCH}
    r = requests.get(url, headers=HEADERS, timeout=TIMEOUT, params=params)
    r.raise_for_status()
    return r.json()

def github_api_get(path):
    """
    Return JSON from GitHub Contents API for a given repo path.
    Path examples:
      - "models/rf_model.pkl"
      - "models/fire_pytorch"
    """
    url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{path}"
    params = {"ref": GITHUB_BRANCH}
    r = requests.get(url, headers=HEADERS, timeout=TIMEOUT, params=params)
    r.raise_for_status()
    return r.json()


def list_github_models():
    items = list_repo_root()
    models = {}

    for item in items:
        name = item["name"]

        # Case 1: single files
        if item["type"] == "file":
            model_name = os.path.splitext(name)[0]   # 'rf_model.pkl' -> 'rf_model'
            models[model_name] = {
                "source": "github",
                "model_name": model_name,
                "type": item["type"],
                "model_path": f"{MODELS_ROOT}/{name}"
            }

        # Case 2: folder-based model
        elif item["type"] == "dir":
            model_name = name
            models[model_name] = {
                "source": "github",
                "model_name": model_name,
                "type": item["type"],
                "model_path": f"{MODELS_ROOT}/{name}"
            }
    
    return models


def download_file(download_url, local_path):
    """ Download a single file using its GitHub download_url. """
    r = requests.get(download_url, timeout=TIMEOUT)
    r.raise_for_status()

    os.makedirs(os.path.dirname(local_path), exist_ok=True)
    with open(local_path, "wb") as f:
        f.write(r.content)


def download_folder(repo_path, local_path):
    """
    Recursively download a GitHub folder.
    """
    items = github_api_get(repo_path)
    os.makedirs(local_path, exist_ok=True)

    for item in items:
        if item["type"] == "file":
            file_path = os.path.join(local_path, item["name"])
            download_file(item["download_url"], file_path)

        elif item["type"] == "dir":
            sub_repo_path = f"{repo_path}/{item['name']}"
            sub_local_path = os.path.join(local_path, item["name"])
            download_folder(sub_repo_path, sub_local_path)

        else:
            raise RuntimeError(f"Unknown GitHub item type: {item['type']}")


def download_github_model(model_entry):
    """
    Download a model from GitHub into /models/<model_name>.
    Can be a single file or a folder.
    """
    repo_path = model_entry["model_path"]
    info = github_api_get(repo_path)

    # Single file
    if isinstance(info, dict) and info.get("type") == "file":
        dest_file = os.path.join("/models", os.path.basename(repo_path))
        download_file(info["download_url"], dest_file)
        return dest_file

    # Directory
    if isinstance(info, list):
        dest_dir = os.path.join("/models", model_entry["model_name"])
        if os.path.exists(dest_dir):
            shutil.rmtree(dest_dir)
        download_folder(repo_path, dest_dir)
        return dest_dir

    # other (unsupported) format
    raise RuntimeError(f"Unsupported GitHub model type for path: {repo_path}")
