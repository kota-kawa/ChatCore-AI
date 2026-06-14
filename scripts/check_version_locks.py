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


# 日本語: パッケージ名のスペルや区切り文字を正規化（小文字化、ハイフン統一）します。
# English: Normalize package names by converting to lowercase and replacing underscores/dots with hyphens.
def normalize_package_name(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


# 日本語: 指定された requirements ファイルを読み込み、完全一致（==）で固定されたパッケージ名とバージョンを解析して辞書として返します。
# English: Read the specified requirements file, parse exact-pinning (==) packages, and return them as a package-to-version mapping dictionary.
def parse_requirements(path: Path) -> dict[str, str]:
    requirements: dict[str, str] = {}
    # 日本語: ファイルの各行を1行ずつ読み込み、空白行やコメント行を除いて処理します。
    # English: Read and process each line of the file, skipping empty lines and comments.
    for line_number, raw_line in enumerate(path.read_text().splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        # 日本語: パッケージ指定が == による完全一致固定（Pinning）になっているか確認します。
        # English: Check if the package specification uses exact matching with == pinning.
        if not EXACT_REQUIREMENT.match(line):
            raise ValueError(f"{path}:{line_number} must use exact == pinning: {raw_line}")
        name, version = line.split("==", 1)
        requirements[normalize_package_name(name)] = version
    return requirements


# 日本語: requirements.txt/build/dev の記述と requirements.lock に記載されているロックバージョンが一致しているかを検証します。
# English: Verify if requirements from runtime/build/dev files match the locked versions in requirements.lock.
def check_python_requirements() -> list[str]:
    errors: list[str] = []
    # 日本語: 各種 requirements ファイルをパースします。解析エラーが発生した場合はエラーメッセージとして捕捉します。
    # English: Parse the various requirements files. Catch value errors if any parsing failure occurs.
    try:
        runtime = parse_requirements(REPO_ROOT / "requirements.txt")
        build = parse_requirements(REPO_ROOT / "requirements-build.txt")
        dev = parse_requirements(REPO_ROOT / "requirements-dev.txt")
        lock = parse_requirements(REPO_ROOT / "requirements.lock")
    except ValueError as exc:
        return [str(exc)]

    # 日本語: 開発用・実行環境用のパッケージ名とバージョンが、ロックファイルと整合しているかチェックします。
    # English: Validate package versions of development and runtime packages against the lock file.
    for name, version in sorted({**runtime, **dev}.items()):
        if name in dev and name not in runtime:
            continue
        locked_version = lock.get(name)
        if locked_version != version:
            errors.append(
                f"requirements.lock must include {name}=={version}; found {locked_version!r}"
            )
    # 日本語: ビルド用のパッケージバージョンがロックファイルと整合しているかチェックします。
    # English: Validate package versions of build requirements against the lock file.
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


# 日本語: 指定されたコンテナイメージ名がローカルビルドイメージであるかどうかを判定します。
# English: Determine whether the given container image name represents a locally built image.
def is_local_image(image: str) -> bool:
    return image.startswith("chat-core-")


# 日本語: 指定されたイメージ名が、具体的なバージョンまたは SHA-256 ダイジェストによって固定（ピン留め）されているかを判定します。
# English: Determine whether the given image name is pinned via a specific version tag or a SHA-256 digest.
def is_pinned_image(image: str) -> bool:
    # 日本語: イメージ名に SHA-256 ハッシュが含まれる場合は、固定済みとみなします。
    # English: If the image name contains a SHA-256 hash, it is considered pinned.
    if "@sha256:" in image:
        return True
    # 日本語: タグ指定がないイメージは、暗黙的に latest になるため未固定とみなします。
    # English: Images without any tag specified default to latest, which is considered unpinned.
    if ":" not in image:
        return False
    repository, tag = image.rsplit(":", 1)
    # 日本語: ローカルのビルドイメージは、開発用のため固定チェックをパスします。
    # English: Locally built images bypass the pinning check since they are for development.
    if is_local_image(repository):
        return True
    # 日本語: latest タグが明示されている場合は未固定とみなします。
    # English: If the latest tag is explicitly specified, it is considered unpinned.
    if tag == "latest":
        return False
    # 日本語: postgres などの一部のイメージはメジャー・マイナーバージョン(例: 15.1)で固定、それ以外はセマンティックバージョニング(例: 1.2.3)で固定されているか判定します。
    # English: Determine if specific images like postgres are pinned with major.minor (e.g. 15.1), and others are pinned with semver (e.g. 1.2.3).
    if repository.endswith("postgres"):
        return re.fullmatch(r"\d+\.\d+", tag) is not None
    return re.search(r"\d+\.\d+\.\d+", tag) is not None


# 日本語: 各種 Dockerfile や docker-compose ファイル内で指定されているコンテナイメージが適切にピン留めされているかをチェックします。
# English: Check if all container images specified in Dockerfiles and docker-compose files are properly pinned.
def check_container_images() -> list[str]:
    errors: list[str] = []
    files = [
        REPO_ROOT / "Dockerfile",
        REPO_ROOT / "frontend" / "Dockerfile",
        REPO_ROOT / "docker-compose.yml",
        REPO_ROOT / "deploy" / "docker-compose.bluegreen.yml",
    ]
    # 日本語: 対象の Dockerfile または YAML ファイルの内容を読み込み、FROM や image 指定を抽出してピン留めされているか判定します。
    # English: Read each target Dockerfile or YAML file, extract FROM/image directives, and verify that they are pinned.
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


# 日本語: フロントエンドの package.json と package-lock.json の間で、パッケージのバージョン指定が厳密かつ一致しているかを検証します。
# English: Verify that the frontend package versions in package.json are exact and match the locked versions in package-lock.json.
def check_frontend_manifest() -> list[str]:
    errors: list[str] = []
    package_json = REPO_ROOT / "frontend" / "package.json"
    package_lock = REPO_ROOT / "frontend" / "package-lock.json"
    package = json.loads(package_json.read_text())
    lock = json.loads(package_lock.read_text())
    root_lock = lock.get("packages", {}).get("", {})

    # 日本語: dependencies と devDependencies セクションのそれぞれについて、バージョン指定をチェックします。
    # English: Check the version specifications for both dependencies and devDependencies sections.
    for section in ("dependencies", "devDependencies"):
        manifest_deps = package.get(section, {})
        lock_deps = root_lock.get(section, {})
        for name, spec in sorted(manifest_deps.items()):
            # 日本語: バージョン指定が範囲やワイルドカード(例: ^, ~, *)を含む変動指定（Floating）になっていないか検証します。
            # English: Verify that the package version specifier is not a floating pattern (e.g. ^, ~, *).
            if FLOATING_NPM_SPEC.match(spec):
                errors.append(f"frontend/package.json {section}.{name} is not exact: {spec}")
            # 日本語: package.json の指定が package-lock.json のルートパッケージロック情報と一致しているか検証します。
            # English: Validate that the specifier in package.json matches the root lock information in package-lock.json.
            if lock_deps.get(name) != spec:
                errors.append(
                    f"frontend/package-lock.json {section}.{name} must match package.json"
                )
    return errors


# 日本語: Python要件、コンテナイメージ、フロントエンド依存関係のすべてに対してバージョン固定チェックを実行するメイン関数です。
# English: Main execution function to run version lock checks across Python requirements, container images, and frontend manifests.
def main() -> int:
    errors = [
        *check_python_requirements(),
        *check_container_images(),
        *check_frontend_manifest(),
    ]
    # 日本語: 検出されたエラーがある場合はエラー詳細を標準エラー出力にプリントし、ステータスコード 1 で終了します。
    # English: If any errors are detected, print them to standard error and return exit status code 1.
    if errors:
        for error in errors:
            print(error, file=sys.stderr)
        return 1
    print("Version locks are configured.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

