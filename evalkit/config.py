"""Environments, run settings and credentials. Nothing in here belongs to a case."""
import json
import os
import subprocess
from dataclasses import dataclass, fields, replace
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


class ConfigError(Exception):
    """A setting or credential is missing or wrong. The message says how to fix it."""


@dataclass(frozen=True)
class Environment:
    name: str
    url: str
    allow_writes: bool = False

    @property
    def token_var(self):
        return f"SH_EVAL_TOKEN_{self.name.upper().replace('-', '_')}"

    def read_token(self):
        token = os.environ.get(self.token_var, "").strip()
        if not token:
            raise ConfigError(
                f"no token for {self.name}: set {self.token_var} in .env "
                "(an agent token, sh_agent_..., from a super admin)")
        return token


def load_dotenv(root=ROOT):
    """Read .env into the process environment. Variables already set win."""
    from dotenv import load_dotenv as _load
    _load(Path(root) / ".env", override=False)


def environment(name, url=None, path=None):
    """The named environment from environments.json. `url` overrides its address, or
    defines a one-off environment (a preview deploy, say) that is not in the file."""
    path = Path(path or ROOT / "environments.json")
    envs = json.loads(path.read_text(encoding="utf-8"))
    if name in envs:
        e = envs[name]
        return Environment(name, url or e["url"], bool(e.get("allow_writes", False)))
    if url:
        return Environment(name, url, allow_writes=False)
    raise ConfigError(f"unknown environment {name!r}; known: {', '.join(sorted(envs))}. "
                      "Add it to environments.json, or pass --url.")


@dataclass(frozen=True)
class Settings:
    model: str = "claude-opus-5-5"
    effort: str = "medium"
    judge_model: str = "claude-opus-5-5"
    judge_effort: str = "high"
    k: int = 3
    max_steps: int = 20


def settings(path=None, **overrides):
    """settings.json, with any override that is not None applied on top."""
    path = Path(path or ROOT / "settings.json")
    raw = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    known = {f.name for f in fields(Settings)}
    unknown = set(raw) - known
    if unknown:
        raise ConfigError(f"{path.name}: unknown setting(s) {', '.join(sorted(unknown))}; "
                          f"known: {', '.join(sorted(known))}")
    s = Settings(**raw)
    return replace(s, **{k: v for k, v in overrides.items() if v is not None})


def skills(root=ROOT):
    """Extra system-prompt text: every skills/*.md except the folder's README."""
    folder = Path(root) / "skills"
    return [p.read_text(encoding="utf-8").strip() for p in sorted(folder.glob("*.md"))
            if p.name.lower() != "readme.md"]


def evalkit_version(root=ROOT):
    """The commit this checkout is on, with +dirty when it has local changes."""
    try:
        sha = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=root,
                             capture_output=True, text=True, check=True).stdout.strip()
        dirty = subprocess.run(["git", "status", "--porcelain"], cwd=root,
                               capture_output=True, text=True, check=True).stdout.strip()
        return sha + ("+dirty" if dirty else "")
    except (OSError, subprocess.CalledProcessError):
        return "unknown"
