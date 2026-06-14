from __future__ import annotations

import json
import re
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).parents[1]
EXACT_REQUIREMENT = re.compile(r"^[A-Za-z0-9_.-]+==[^<>=!~]+$")
DOCKER_FROM = re.compile(r"^\s*FROM\s+(?P<image>\S+)", re.MULTILINE)
COMPOSE_IMAGE = re.compile(r"^\s*image:\s+(?P<image>\S+)", re.MULTILINE)
FLOATING_NPM_SPEC = re.compile(r"^(?:[\^~*]|[<>]=?|latest$|x$|X$)", re.IGNORECASE)


# 日本語: normalize package name の正規化処理を担当します。
# English: Handle normalizing for normalize package name.
def normalize_package_name(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


# 日本語: parse requirements の解析処理を担当します。
# English: Handle parsing for parse requirements.
def parse_requirements(path: Path) -> dict[str, str]:
    requirements: dict[str, str] = {}
    # 日本語: 対象データを順番に処理し、必要な結果を積み上げます。
    # English: Process each target item in order and accumulate the needed result.
    for line_number, raw_line in enumerate(path.read_text().splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if not EXACT_REQUIREMENT.match(line):
            raise ValueError(f"{path}:{line_number} must use exact == pinning: {raw_line}")
        name, version = line.split("==", 1)
        requirements[normalize_package_name(name)] = version
    return requirements


# 日本語: check python requirements の確認処理を担当します。
# English: Handle checking for check python requirements.
def check_python_requirements() -> list[str]:
    errors: list[str] = []
    # 日本語: 失敗する可能性がある処理を捕捉できる形で実行します。
    # English: Run potentially failing work in a form that can be caught.
    try:
        runtime = parse_requirements(REPO_ROOT / "requirements.txt")
        build = parse_requirements(REPO_ROOT / "requirements-build.txt")
        dev = parse_requirements(REPO_ROOT / "requirements-dev.txt")
        lock = parse_requirements(REPO_ROOT / "requirements.lock")
    except ValueError as exc:
        return [str(exc)]

    # 日本語: 対象データを順番に処理し、必要な結果を積み上げます。
    # English: Process each target item in order and accumulate the needed result.
    for name, version in sorted({**runtime, **dev}.items()):
        if name in dev and name not in runtime:
            continue
        locked_version = lock.get(name)
        if locked_version != version:
            errors.append(
                f"requirements.lock must include {name}=={version}; found {locked_version!r}"
            )
    for name, version in sorted(build.items()):
        if name in {"pip", "setuptools", "wheel"}:
            continue
        locked_version = lock.get(name)
        if locked_version != version:
            errors.append(
                f"requirements.lock must include build package {name}=={version}; "
                f"found {locked_version!r}"
            )
    return errors


# 日本語: is local image に関する処理の入口です。
# English: Entry point for logic related to is local image.
def is_local_image(image: str) -> bool:
    return image.startswith("chat-core-")


# 日本語: is pinned image に関する処理の入口です。
# English: Entry point for logic related to is pinned image.
def is_pinned_image(image: str) -> bool:
    # 日本語: 現在の条件に合わせて処理の流れを切り替えます。
    # English: Switch the flow according to the current condition.
    if "@sha256:" in image:
        return True
    # 日本語: 現在の条件に合わせて処理の流れを切り替えます。
    # English: Switch the flow according to the current condition.
    if ":" not in image:
        return False
    repository, tag = image.rsplit(":", 1)
    if is_local_image(repository):
        return True
    if tag == "latest":
        return False
    if repository.endswith("postgres"):
        return re.fullmatch(r"\d+\.\d+", tag) is not None
    return re.search(r"\d+\.\d+\.\d+", tag) is not None


# 日本語: check container images の確認処理を担当します。
# English: Handle checking for check container images.
def check_container_images() -> list[str]:
    errors: list[str] = []
    files = [
        REPO_ROOT / "Dockerfile",
        REPO_ROOT / "frontend" / "Dockerfile",
        REPO_ROOT / "docker-compose.yml",
        REPO_ROOT / "deploy" / "docker-compose.bluegreen.yml",
    ]
    # 日本語: 対象データを順番に処理し、必要な結果を積み上げます。
    # English: Process each target item in order and accumulate the needed result.
    for path in files:
        text = path.read_text()
        images = [
            *DOCKER_FROM.findall(text),
            *COMPOSE_IMAGE.findall(text),
        ]
        for image in images:
            if not is_pinned_image(image):
                errors.append(f"{path.relative_to(REPO_ROOT)} uses an unpinned image: {image}")
    return errors


# 日本語: check frontend manifest の確認処理を担当します。
# English: Handle checking for check frontend manifest.
def check_frontend_manifest() -> list[str]:
    errors: list[str] = []
    package_json = REPO_ROOT / "frontend" / "package.json"
    package_lock = REPO_ROOT / "frontend" / "package-lock.json"
    package = json.loads(package_json.read_text())
    lock = json.loads(package_lock.read_text())
    root_lock = lock.get("packages", {}).get("", {})

    # 日本語: 対象データを順番に処理し、必要な結果を積み上げます。
    # English: Process each target item in order and accumulate the needed result.
    for section in ("dependencies", "devDependencies"):
        manifest_deps = package.get(section, {})
        lock_deps = root_lock.get(section, {})
        for name, spec in sorted(manifest_deps.items()):
            if FLOATING_NPM_SPEC.match(spec):
                errors.append(f"frontend/package.json {section}.{name} is not exact: {spec}")
            if lock_deps.get(name) != spec:
                errors.append(
                    f"frontend/package-lock.json {section}.{name} must match package.json"
                )
    return errors


# 日本語: main に関する処理の入口です。
# English: Entry point for logic related to main.
def main() -> int:
    errors = [
        *check_python_requirements(),
        *check_container_images(),
        *check_frontend_manifest(),
    ]
    # 日本語: 現在の条件に合わせて処理の流れを切り替えます。
    # English: Switch the flow according to the current condition.
    if errors:
        for error in errors:
            print(error, file=sys.stderr)
        return 1
    print("Version locks are configured.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
