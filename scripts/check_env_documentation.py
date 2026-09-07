from __future__ import annotations

import ast
import sys
from collections.abc import Iterable, Iterator, Mapping
from pathlib import Path
from typing import TypeGuard

REPO_ROOT = Path(__file__).parents[1]

# 日本語: 実行時に環境変数を読むコードの探索範囲です。テストやスクリプトは実行時経路ではないため含めません。
# English: Source roots scanned for runtime environment reads. Tests and scripts are not runtime paths, so they are excluded.
RUNTIME_SOURCES = ("app.py", "blueprints", "services")

# 日本語: 環境変数を直接読む属性名です。`dep("os").getenv(...)` のような間接呼び出しも受け側を問わず一致させます。
# English: Attribute names that read the environment directly.
#          Indirect calls such as `dep("os").getenv(...)` match regardless of the receiver.
DIRECT_READ_ATTRIBUTES = frozenset({"getenv"})

# 日本語: ヘルパー関数を「環境変数読み取り関数」と判定するための第1引数名です。
# English: First-parameter names that mark a helper function as an environment reader.
NAME_PARAMETERS = frozenset({"name", "key", "var", "env_name", "variable"})

# 日本語: Python の実行時コードからは読まれず、Docker／デプロイ側だけで使う変数の許可リストです。
#         各エントリーに用途を書き、`.env.example` に残す理由を明示します。
# English: Allowlist for variables that no runtime Python code reads but Docker/deploy still needs.
#          Each entry records its purpose so the reason for keeping it in `.env.example` stays explicit.
DEPLOY_ONLY_VARIABLES: dict[str, str] = {
    # 日本語: docker-compose が postgres の起動コマンド引数（-c フラグ）へ展開するチューニング値です。
    # English: Expanded by docker-compose into the postgres startup command arguments (-c flags).
    "POSTGRES_SHARED_BUFFERS": "docker-compose.yml / deploy: postgres -c tuning flag",
    "POSTGRES_EFFECTIVE_CACHE_SIZE": "docker-compose.yml / deploy: postgres -c tuning flag",
    "POSTGRES_WORK_MEM": "docker-compose.yml / deploy: postgres -c tuning flag",
    "POSTGRES_MAINTENANCE_WORK_MEM": "docker-compose.yml / deploy: postgres -c tuning flag",
    "POSTGRES_LOG_MIN_DURATION_MS": "docker-compose.yml / deploy: postgres -c tuning flag",
    # 日本語: docker-compose が redis の起動コマンド引数へ展開する上限値です。
    # English: Expanded by docker-compose into the redis startup command arguments.
    "REDIS_MAXMEMORY": "docker-compose.yml / deploy: redis --maxmemory flag",
    # 日本語: Next.js のビルド時／クライアント側でのみ読まれる公開変数です（Python 側では読みません）。
    # English: Public variables read only by the Next.js build and client, never by Python.
    "NEXT_PUBLIC_SITE_URL": "frontend/lib/seo.ts: canonical URL, sitemap and OG URL",
    "NEXT_PUBLIC_TWITTER_SITE": "frontend/lib/seo.ts: X (Twitter) site handle",
    "NEXT_PUBLIC_GA_MEASUREMENT_ID": "frontend: Google Analytics measurement ID",
}

# 日本語: 変数名を実行時に組み立てるため、静的に列挙できないモジュールの許可リストです。
#         `.env.example` ではコメントとして命名規則を説明し、`KEY=` 行は持ちません。
# English: Allowlist for modules that build variable names at runtime and cannot be enumerated statically.
#          `.env.example` explains the naming rule in a comment and carries no `KEY=` line for them.
DYNAMIC_NAME_MODULES: dict[str, str] = {
    # 日本語: `LLM_CONTEXT_WINDOW_<MODEL>` のモデル別上書きを、モデル名から組み立てます。
    # English: Builds the per-model `LLM_CONTEXT_WINDOW_<MODEL>` override from the model name.
    "services/llm_context_budget.py": "per-model LLM_CONTEXT_WINDOW_<MODEL> overrides",
}


# 日本語: 走査対象の Python ファイルを列挙します。`__pycache__` などの生成物は除外します。
# English: Enumerate the Python files to scan, skipping generated directories such as `__pycache__`.
def iter_python_files(roots: Iterable[Path]) -> Iterator[Path]:
    for root in roots:
        if root.is_file() and root.suffix == ".py":
            yield root
            continue
        if not root.is_dir():
            continue
        for path in sorted(root.rglob("*.py")):
            if "__pycache__" in path.parts:
                continue
            yield path


# 日本語: `os.environ` を指す式かどうかを判定します。
# English: Report whether the expression refers to `os.environ`.
def _is_os_environ(node: ast.expr) -> bool:
    return isinstance(node, ast.Attribute) and node.attr == "environ"


# 日本語: `os.environ[...]` の読み取りだけを対象にします。アプリ自身が値を設定する代入は設定項目ではないため除外します。
# English: Match only reads of `os.environ[...]`.
#          An assignment where the app sets the value itself is not a configuration knob, so it is excluded.
def _is_environ_read_subscript(node: ast.AST) -> TypeGuard[ast.Subscript]:
    return isinstance(node, ast.Subscript) and _is_os_environ(node.value) and isinstance(node.ctx, ast.Load)


# 日本語: 呼び出しが環境変数の直接読み取り（`os.getenv` / `os.environ.get`）かどうかを判定します。
# English: Report whether a call is a direct environment read (`os.getenv` / `os.environ.get`).
def _is_direct_read_call(node: ast.Call) -> bool:
    func = node.func
    if not isinstance(func, ast.Attribute):
        return False
    if func.attr in DIRECT_READ_ATTRIBUTES:
        return True
    return func.attr == "get" and _is_os_environ(func.value)


# 日本語: 呼び出し先の関数名を取り出します。`self.method(...)` のような属性呼び出しも末尾の名前で扱います。
# English: Extract the callee's function name, using the trailing name for attribute calls such as `self.method(...)`.
def _callee_name(node: ast.Call) -> str | None:
    if isinstance(node.func, ast.Name):
        return node.func.id
    if isinstance(node.func, ast.Attribute):
        return node.func.attr
    return None


# 日本語: 関数本体が環境変数を読んでいるか、または既知の読み取りヘルパーを呼んでいるかを判定します。
# English: Report whether a function body reads the environment or delegates to a known reader helper.
def _body_reads_environment(func: ast.AST, known_readers: frozenset[str]) -> bool:
    for node in ast.walk(func):
        if _is_environ_read_subscript(node):
            return True
        if not isinstance(node, ast.Call):
            continue
        if _is_direct_read_call(node):
            return True
        if _callee_name(node) in known_readers:
            return True
    return False


# 日本語: 第1引数として変数名を受け取り、その名前で環境変数を読むヘルパー関数を収集します。
#         同名でも値を受け取るだけのヘルパー（例: `_positive_int(value, default)`）は除外するため、
#         判定はファイル単位で行い、名前解決を取り違えないようにします。
# English: Collect helper functions that take a variable name as their first argument and read that variable.
#          Helpers that merely take a value (for example `_positive_int(value, default)`) are excluded, so the
#          detection is per-file to avoid resolving a name against the wrong definition.
def collect_reader_functions(tree: ast.AST, imported_readers: frozenset[str]) -> frozenset[str]:
    readers = set(imported_readers)
    # 日本語: ヘルパーがさらに別のヘルパーへ委譲する場合に備え、集合が安定するまで繰り返します。
    # English: Repeat until the set stabilizes, in case one helper delegates to another.
    while True:
        discovered = set(readers)
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                continue
            if node.name in discovered:
                continue
            parameters = node.args.posonlyargs + node.args.args + node.args.kwonlyargs
            if not any(argument.arg in NAME_PARAMETERS for argument in parameters):
                continue
            if _body_reads_environment(node, frozenset(discovered)):
                discovered.add(node.name)
        if discovered == readers:
            return frozenset(readers)
        readers = discovered


# 日本語: モジュール直下の `X = partial(reader, ...)` のような束縛を解決し、`X` も読み取りヘルパーとして扱います。
#         引数を部分適用したエイリアス経由で環境変数を読むコードを取りこぼさないための対応です。
# English: Resolve module-level bindings such as `X = partial(reader, ...)` so `X` counts as a reader helper too.
#          This keeps code that reads the environment through a partially-applied alias from being missed.
def collect_partial_aliases(tree: ast.AST, readers: frozenset[str]) -> frozenset[str]:
    aliases: set[str] = set()
    for statement in getattr(tree, "body", []):
        if not isinstance(statement, ast.Assign) or not isinstance(statement.value, ast.Call):
            continue
        call = statement.value
        if _callee_name(call) != "partial" or not call.args:
            continue
        wrapped = call.args[0]
        wrapped_name = wrapped.id if isinstance(wrapped, ast.Name) else getattr(wrapped, "attr", None)
        if wrapped_name not in readers:
            continue
        for target in statement.targets:
            if isinstance(target, ast.Name):
                aliases.add(target.id)
    return frozenset(aliases)


# 日本語: 他モジュールから import された読み取りヘルパー名を解決します。
# English: Resolve reader-helper names that were imported from another module.
def collect_imported_readers(tree: ast.AST, module_readers: Mapping[Path, frozenset[str]]) -> frozenset[str]:
    exported = {name for names in module_readers.values() for name in names}
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            for alias in node.names:
                if alias.name in exported:
                    imported.add(alias.asname or alias.name)
    return frozenset(imported)


# 日本語: モジュール直下で文字列リテラルへ束縛された定数を集めます（例: `RESEND_API_KEY_ENV = "RESEND_API_KEY"`）。
#         環境変数名を定数経由で渡すコードを解決するために使います。
# English: Collect module-level constants bound to a string literal (for example `RESEND_API_KEY_ENV = "RESEND_API_KEY"`),
#          so code that passes the variable name through a constant can be resolved.
def collect_string_constants(tree: ast.AST) -> dict[str, str]:
    constants: dict[str, str] = {}
    body = getattr(tree, "body", [])
    for statement in body:
        if isinstance(statement, ast.Assign):
            targets = statement.targets
            value = statement.value
        elif isinstance(statement, ast.AnnAssign) and statement.value is not None:
            targets = [statement.target]
            value = statement.value
        else:
            continue
        if not (isinstance(value, ast.Constant) and isinstance(value.value, str)):
            continue
        for target in targets:
            if isinstance(target, ast.Name):
                constants[target.id] = value.value
    return constants


# 日本語: 単一ファイルから、読み取られている環境変数名と、名前を解決できなかった箇所を抽出します。
# English: Extract the environment variable names read by one file, plus the sites whose name could not be resolved.
def read_names_in_file(
    path: Path,
    tree: ast.AST,
    readers: frozenset[str],
) -> tuple[set[str], list[str]]:
    names: set[str] = set()
    unresolved: list[str] = []
    constants = collect_string_constants(tree)

    # 日本語: 文字列リテラル、または文字列定数への参照なら採用します。
    #         読み取りヘルパー自身が受け取った引数の転送は、呼び出し側で解決済みのため無視します。
    #         それ以外（f-string など動的に組み立てる名前）は未解決として報告します。
    # English: Accept a string literal or a reference to a string constant.
    #          Skip a reader helper forwarding its own parameter, which is already resolved at the call site.
    #          Anything else (an f-string or another computed name) is reported as unresolved.
    def record(argument: ast.expr | None, line: int) -> None:
        if isinstance(argument, ast.Constant) and isinstance(argument.value, str):
            names.add(argument.value)
            return
        if isinstance(argument, ast.Name):
            if argument.id in constants:
                names.add(constants[argument.id])
                return
            if argument.id in NAME_PARAMETERS:
                return
        unresolved.append(f"{path}:{line}: environment variable name could not be resolved statically")

    for node in ast.walk(tree):
        if _is_environ_read_subscript(node):
            record(node.slice, node.lineno)
            continue
        if not isinstance(node, ast.Call):
            continue
        # 日本語: 環境変数を読む呼び出しに限って、位置引数の先頭と `env_name=` のようなキーワード引数から名前を取り出します。
        #         ここで絞らないと、無関係な `name=` 引数まで環境変数名として拾ってしまいます。
        # English: Only for calls that actually read the environment, take the name from the first positional argument
        #          and from keyword arguments such as `env_name=`. Without this gate, unrelated `name=` arguments would be picked up.
        if not (_is_direct_read_call(node) or _callee_name(node) in readers):
            continue
        if node.args:
            record(node.args[0], node.lineno)
        for keyword in node.keywords:
            if keyword.arg in NAME_PARAMETERS:
                record(keyword.value, node.lineno)

    return names, unresolved


# 日本語: 実行時コードが読む環境変数名の集合と、名前を解決できなかった箇所を返します。
# English: Return the set of environment variable names read by runtime code, plus any unresolved sites.
def collect_runtime_variables(repo_root: Path, sources: Iterable[str] = RUNTIME_SOURCES) -> tuple[set[str], list[str]]:
    paths = list(iter_python_files(repo_root / source for source in sources))
    trees: dict[Path, ast.AST] = {}
    for path in paths:
        try:
            trees[path] = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except SyntaxError as exc:
            return set(), [f"{path}: could not be parsed: {exc}"]

    # 日本語: まず各ファイル内で定義された読み取りヘルパーを集め、次に import 経由の名前を解決します。
    # English: First collect the reader helpers defined in each file, then resolve names reached through imports.
    module_readers = {path: collect_reader_functions(tree, frozenset()) for path, tree in trees.items()}
    names: set[str] = set()
    unresolved: list[str] = []
    for path, tree in trees.items():
        imported = collect_imported_readers(tree, module_readers)
        readers = collect_reader_functions(tree, imported)
        # 日本語: partial で束縛したエイリアスを加えたうえで、もう一度ヘルパーを解決します。
        # English: Add the partial-bound aliases, then resolve the helpers once more.
        readers = collect_reader_functions(tree, readers | collect_partial_aliases(tree, readers))
        file_names, file_unresolved = read_names_in_file(path, tree, readers)
        names |= file_names
        # 日本語: 動的な名前組み立てが既知のモジュールは、未解決として扱いません。
        # English: Modules with a known dynamic naming rule are not reported as unresolved.
        if path.relative_to(repo_root).as_posix() not in DYNAMIC_NAME_MODULES:
            unresolved.extend(file_unresolved)
    return names, unresolved


# 日本語: `.env.example` から 記載されている変数名を抽出します。`KEY=value` 形式の行だけを対象にします。
# English: Extract documented variable names from `.env.example`, considering only `KEY=value` lines.
def parse_env_example(path: Path) -> set[str]:
    documented: set[str] = set()
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[len("export ") :].lstrip()
        key = line.split("=", 1)[0].strip()
        if key:
            documented.add(key)
    return documented


# 日本語: 実行時に読まれる変数と `.env.example` の記載が一致しているかを検証します。
# English: Verify that the runtime-read variables and the `.env.example` entries agree.
def check_documentation(repo_root: Path) -> list[str]:
    env_example = repo_root / ".env.example"
    if not env_example.is_file():
        return [f"{env_example} is missing"]

    runtime, unresolved = collect_runtime_variables(repo_root)
    documented = parse_env_example(env_example)

    allowlisted = set(DEPLOY_ONLY_VARIABLES)
    return [
        *unresolved,
        *(f"{name} is read by runtime code but missing from .env.example" for name in sorted(runtime - documented - allowlisted)),
        *(f"{name} is documented in .env.example but nothing reads it" for name in sorted(documented - runtime - allowlisted)),
    ]


# 日本語: 検証を実行し、差分があればエラーを標準エラー出力へ書き出して終了コード 1 を返します。
# English: Run the check and, when anything is out of sync, print the errors to standard error and return exit code 1.
def main() -> int:
    errors = check_documentation(REPO_ROOT)
    if errors:
        for error in errors:
            print(error, file=sys.stderr)
        return 1
    print(".env.example documents every runtime environment variable.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
