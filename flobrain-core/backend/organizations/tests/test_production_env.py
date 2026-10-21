"""Boot settings the way the ECS task does: only the production env names."""

import json
import os
import subprocess
import sys
from pathlib import Path

from django.test import SimpleTestCase

BACKEND = Path(__file__).resolve().parents[2]

# Names present on the production task definition. Values here are dummies.
PRODUCTION_ENV = {
    "AWS_REGION": "us-east-1",
    "DB_PORT": "5432",
    "DB_PASS": "dummy-db-pass",
    "DB_USER": "dummy_user",
    "DB_NAME": "dummy_db",
    "DB_HOST": "127.0.0.1",
    "MULTIMODAL_SERVICE_URL": "http://127.0.0.1:9",
    "CSRF_TRUSTED_ORIGINS": "https://api.flobrain.ai",
    "ALLOWED_HOSTS": "*",
    "SECRET_KEY": "dummy-production-secret-key-at-least-32-bytes",
    "DEBUG": "False",
    "AWS_STORAGE_BUCKET_NAME": "dummy-uploads",
}

_BOOT = r"""
import json, os, sys
spec = json.loads(os.environ["FLOBRAIN_BOOT_JSON"])
keep = {}
for key in ("PATH", "SYSTEMROOT", "WINDIR", "COMSPEC", "PATHEXT", "TEMP", "TMP", "USERPROFILE"):
    if key in os.environ:
        keep[key] = os.environ[key]
os.environ.clear()
os.environ.update(keep)
os.environ.update(spec)
import dotenv
dotenv.load_dotenv = lambda *a, **k: False
os.environ["DJANGO_SETTINGS_MODULE"] = "flobrain.settings"
import django
django.setup()
from django.conf import settings
from django.core.management import call_command
from django.core.management.base import SystemCheckError
print("CORS", ",".join(settings.CORS_ALLOWED_ORIGINS))
print("DEBUG", settings.DEBUG)
print("NUM_PROXIES", "" if settings.NUM_PROXIES is None else settings.NUM_PROXIES)
print("FRONTEND", settings.FRONTEND_BASE_URL)
print("HR_SET", bool(settings.HR_WEBHOOK_SECRET))
print("CRED_SET", bool(settings.CREDENTIALS_ENCRYPTION_KEY))
print("JOBS_EAGER", settings.JOBS_EAGER)
try:
    call_command("check")
except SystemCheckError as exc:
    print("CHECK_FAIL")
    print(exc)
    sys.exit(2)
print("CHECK_OK")
"""


def _boot(extra):
    env = {}
    for key in ("PATH", "SYSTEMROOT", "WINDIR", "COMSPEC", "PATHEXT", "TEMP", "TMP", "USERPROFILE"):
        if key in os.environ:
            env[key] = os.environ[key]
    env["FLOBRAIN_BOOT_JSON"] = json.dumps({**PRODUCTION_ENV, **extra})
    env["PYTHONIOENCODING"] = "utf-8"
    return subprocess.run(
        [sys.executable, "-c", _BOOT],
        cwd=BACKEND,
        env=env,
        capture_output=True,
        text=True,
        timeout=90,
        check=False,
    )


class ProductionEnvBootTests(SimpleTestCase):
    def test_production_names_fail_closed_without_aes_or_cors(self):
        proc = _boot({})
        self.assertEqual(proc.returncode, 2, proc.stdout + proc.stderr)
        self.assertIn("CHECK_FAIL", proc.stdout)
        self.assertIn("flobrain.E001", proc.stdout)
        self.assertIn("http://localhost:3000", proc.stdout)
        self.assertNotIn("https://flobrain.ai", proc.stdout)
        self.assertIn("FRONTEND http://localhost:3000", proc.stdout)
        self.assertIn("HR_SET False", proc.stdout)
        self.assertIn("CRED_SET False", proc.stdout)
        self.assertIn("NUM_PROXIES ", proc.stdout)
        self.assertIn("JOBS_EAGER False", proc.stdout)

    def test_starts_and_allows_production_origin_when_cors_is_set(self):
        proc = _boot(
            {
                "CORS_ALLOWED_ORIGINS": "https://flobrain.ai,https://www.flobrain.ai",
                "ALLOW_INSECURE_AES_MASTER_KEY": "1",
            }
        )
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn("CHECK_OK", proc.stdout)
        self.assertIn("https://flobrain.ai", proc.stdout)
        self.assertIn("https://www.flobrain.ai", proc.stdout)
        self.assertIn("DEBUG False", proc.stdout)
