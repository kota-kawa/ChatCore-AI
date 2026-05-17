import re
import subprocess
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).parents[2]
DEPLOY_SCRIPT = REPO_ROOT / "deploy" / "blue_green_deploy.sh"
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "tests.yml"


class DeployHardeningTest(unittest.TestCase):
    def test_deploy_script_has_valid_bash_syntax(self):
        subprocess.run(["bash", "-n", str(DEPLOY_SCRIPT)], check=True)

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

    def test_deploy_script_uses_noninteractive_sudo_and_db_query_wait(self):
        script_text = DEPLOY_SCRIPT.read_text()

        self.assertIn("sudo -n", script_text)
        self.assertIn("require_noninteractive_sudo", script_text)
        self.assertIn("wait_for_postgres_accepting_queries", script_text)
        self.assertIn('psql -h 127.0.0.1', script_text)

    def test_workflow_forwards_nginx_test_command_to_remote_deploy(self):
        workflow_text = WORKFLOW.read_text()

        self.assertIn("NGINX_TEST_CMD: ${{ secrets.NGINX_TEST_CMD }}", workflow_text)
        self.assertIn("NGINX_TEST_CMD", workflow_text)
        self.assertIn("remote_env_names", workflow_text)
        self.assertIn("NGINX_TEST_CMD=<set>", workflow_text)
        self.assertIn("NGINX_TEST_CMD=<unset>", workflow_text)


if __name__ == "__main__":
    unittest.main()
