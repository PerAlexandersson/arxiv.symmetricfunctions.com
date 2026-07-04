import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CRON_SCRIPT = ROOT / 'cron_update.sh'


class CronUpdateScriptTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.script = CRON_SCRIPT.read_text()

    def test_script_has_valid_bash_syntax(self):
        result = subprocess.run(
            ['bash', '-n', str(CRON_SCRIPT)],
            cwd=ROOT,
            text=True,
            capture_output=True,
        )
        self.assertEqual('', result.stderr)
        self.assertEqual(0, result.returncode)

    def test_uses_locking_and_timestamped_log(self):
        self.assertIn('flock -n 9', self.script)
        self.assertIn('LOCK_FALLBACK="$LOCK_FILE.d"', self.script)
        self.assertIn("date -Is", self.script)
        self.assertIn('LOG_FILE="$LOG_DIR/arxiv-update.log"', self.script)

    def test_runs_fetch_then_doi_lookup_with_overrides(self):
        self.assertIn('FETCH_DAYS="${FETCH_DAYS:-3}"', self.script)
        self.assertIn('DOI_BATCH="${DOI_BATCH:-50}"', self.script)
        self.assertIn('DOI_MIN_AGE="${DOI_MIN_AGE:-30}"', self.script)
        self.assertIn('DOI_RECHECK="${DOI_RECHECK:-180}"', self.script)
        self.assertIn(
            'python3 src/fetch_arxiv.py --recent --days "$FETCH_DAYS"',
            self.script,
        )
        self.assertIn('python3 src/doi_lookup.py "${doi_args[@]}"', self.script)

    def test_auto_approve_can_be_disabled(self):
        self.assertIn('DOI_AUTO_APPROVE="${DOI_AUTO_APPROVE:-0.95}"', self.script)
        self.assertIn('[ "$DOI_AUTO_APPROVE" != "none" ]', self.script)
        self.assertIn('doi_args+=(--auto-approve "$DOI_AUTO_APPROVE")', self.script)


if __name__ == '__main__':
    unittest.main()
