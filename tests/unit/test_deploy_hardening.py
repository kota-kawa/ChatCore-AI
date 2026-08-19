import re
import subprocess
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).parents[2]
DEPLOY_SCRIPT = REPO_ROOT / "deploy" / "blue_green_deploy.sh"
COMPOSE_FILE = REPO_ROOT / "docker-compose.yml"
BLUE_GREEN_COMPOSE_FILE = REPO_ROOT / "deploy" / "docker-compose.bluegreen.yml"
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "tests.yml"
NGINX_CONFIG = REPO_ROOT / "deploy" / "chatcore-ai.conf"


# 日本語: DeployHardeningTest のテストケースをまとめます。
# English: Group test cases for DeployHardeningTest.
class DeployHardeningTest(unittest.TestCase):
    # 日本語: デプロイscripthas有効なbashsyntaxことを検証します。
    # English: Verify that deploy script has valid bash syntax.
    def test_deploy_script_has_valid_bash_syntax(self):
        subprocess.run(["bash", "-n", str(DEPLOY_SCRIPT)], check=True)

    # 日本語: bracedenvreferencesが〜しないflaggedasunresolvedことを検証します。
    # English: Verify that braced env references are not flagged as unresolved.
    def test_braced_env_references_are_not_flagged_as_unresolved(self):
        script_text = DEPLOY_SCRIPT.read_text()
        match = re.search(
            r"^is_empty_or_unresolved\(\) \{\n.*?\n\}",
            script_text,
            flags=re.MULTILINE | re.DOTALL,
        )
        self.assertIsNotNone(match)

        bash_script = (
            f"{match.group(0)}\n"
            "is_empty_or_unresolved '' || exit 1\n"
            "is_empty_or_unresolved '$POSTGRES_DB' || exit 2\n"
            "! is_empty_or_unresolved '${POSTGRES_DB}' || exit 3\n"
            "! is_empty_or_unresolved 'chatcore' || exit 4\n"
        )
        subprocess.run(["bash", "-c", bash_script], check=True)

    # 日本語: およびDBクエリwait、デプロイscriptusesnoninteractivesudoことを検証します。
    # English: Verify that deploy script uses noninteractive sudo and db query wait.
    def test_deploy_script_uses_noninteractive_sudo_and_db_query_wait(self):
        script_text = DEPLOY_SCRIPT.read_text()

        self.assertIn("sudo -n", script_text)
        self.assertIn("require_noninteractive_sudo", script_text)
        self.assertIn("wait_for_postgres_accepting_queries", script_text)
        self.assertIn('psql -h 127.0.0.1', script_text)

    # 日本語: MCP設定が通常構成と本番Blue/Green構成の両方でアプリへ渡されることを検証します。
    # English: Verify that both Compose configurations pass MCP settings to the app.
    def test_compose_files_forward_mcp_environment(self):
        expected_entries = (
            "MCP_ENABLED=${MCP_ENABLED:-false}",
            "MCP_PUBLIC_BASE_URL=${MCP_PUBLIC_BASE_URL:-https://chatcore-ai.com}",
            "MCP_OAUTH_ENCRYPTION_KEYS=${MCP_OAUTH_ENCRYPTION_KEYS:-}",
            "MCP_ALLOWED_ORIGINS=${MCP_ALLOWED_ORIGINS:-}",
            "MCP_DCR_RATE_LIMIT_PER_HOUR=${MCP_DCR_RATE_LIMIT_PER_HOUR:-20}",
            "MCP_MACHINE_MAX_BODY_BYTES=${MCP_MACHINE_MAX_BODY_BYTES:-65536}",
        )

        for compose_file in (COMPOSE_FILE, BLUE_GREEN_COMPOSE_FILE):
            compose_text = compose_file.read_text()
            for entry in expected_entries:
                with self.subTest(compose_file=compose_file.name, entry=entry):
                    self.assertIn(entry, compose_text)

    # 日本語: 通常構成とBlue/Green構成が同じ明示名volumeをアプリへmountすることを確認します。
    # English: Verify standard and blue/green apps mount the same explicitly named upload volume.
    def test_compose_files_persist_prompt_share_uploads(self):
        expected_entries = (
            "PROMPT_SHARE_UPLOAD_DIR=/app/data/uploads/prompt_share",
            "PROMPT_SHARE_ATTACHMENT_USER_QUOTA_BYTES=${PROMPT_SHARE_ATTACHMENT_USER_QUOTA_BYTES:-104857600}",
            "prompt_share_uploads:/app/data/uploads/prompt_share",
            "name: ${PROMPT_SHARE_UPLOAD_VOLUME:-chatcore-ai_prompt_share_uploads}",
        )

        for compose_file in (COMPOSE_FILE, BLUE_GREEN_COMPOSE_FILE):
            compose_text = compose_file.read_text()
            for entry in expected_entries:
                with self.subTest(compose_file=compose_file.name, entry=entry):
                    self.assertIn(entry, compose_text)

        blue_green_text = BLUE_GREEN_COMPOSE_FILE.read_text()
        self.assertIn("app_blue: &app_service", blue_green_text)
        self.assertRegex(blue_green_text, r"app_green:\s+<<: \*app_service")

    # 日本語: 初回デプロイが旧コンテナ層の画像を新volumeへ非上書き移行してから停止することを確認します。
    # English: Verify initial deploy copies legacy container uploads without overwrite before teardown.
    def test_deploy_migrates_legacy_prompt_share_uploads_before_container_teardown(self):
        script_text = DEPLOY_SCRIPT.read_text()

        self.assertIn("migrate_legacy_prompt_share_uploads()", script_text)
        self.assertIn("docker cp", script_text)
        self.assertIn("cp -a -n /legacy/. /uploads/", script_text)
        self.assertIn(".legacy_container_migration_complete", script_text)
        self.assertIn(
            '[[ ! "${volume_name}" =~ ^[A-Za-z0-9][A-Za-z0-9_.-]*$ ]]',
            script_text,
        )
        self.assertLess(
            script_text.index("migrate_legacy_prompt_share_uploads\nupgrade_postgres_if_required"),
            script_text.index("start_core_services\n"),
        )

    # 日本語: MCP有効時には暗号鍵を必須設定として検証することを確認します。
    # English: Verify that deployment requires the encryption key when MCP is enabled.
    def test_deploy_requires_mcp_encryption_key_when_enabled(self):
        script_text = DEPLOY_SCRIPT.read_text()

        self.assertIn('local mcp_enabled="${MCP_ENABLED:-false}"', script_text)
        self.assertIn("required_vars+=(MCP_OAUTH_ENCRYPTION_KEYS)", script_text)

    # 日本語: OAuth discovery のルート版とMCPリソース版を両方バックエンドへ転送することを確認します。
    # English: Verify nginx forwards both root and MCP-resource OAuth discovery paths.
    def test_nginx_forwards_both_mcp_protected_resource_metadata_paths(self):
        config_text = NGINX_CONFIG.read_text()

        self.assertIn(r"\.well-known/oauth-protected-resource(?:/mcp)?", config_text)

    def test_nginx_applies_a_narrow_upload_limit_to_prompt_publish(self):
        config_text = NGINX_CONFIG.read_text()

        self.assertIn("location = /prompt_share/api/prompts", config_text)
        self.assertIn("client_max_body_size 6m;", config_text)

    # 日本語: remoteデプロイへ、workflowforwardsnginxtestcommandことを検証します。
    # English: Verify that workflow forwards nginx test command to remote deploy.
    def test_workflow_forwards_nginx_test_command_to_remote_deploy(self):
        workflow_text = WORKFLOW.read_text()

        self.assertIn("version_lock_check", workflow_text)
        self.assertIn("NGINX_TEST_CMD: ${{ secrets.NGINX_TEST_CMD }}", workflow_text)
        self.assertIn("NGINX_TEST_CMD", workflow_text)
        self.assertIn("remote_env_names", workflow_text)
        self.assertIn("NGINX_TEST_CMD=<set>", workflow_text)
        self.assertIn("NGINX_TEST_CMD=<unset>", workflow_text)


if __name__ == "__main__":
    unittest.main()
