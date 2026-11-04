import os
import sqlite3
import subprocess
import zipfile
from datetime import datetime
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Back up the database and private files into backups/, and delete old backups"

    def add_arguments(self, parser):
        parser.add_argument("--keep", type=int, default=14, help="How many backups to keep")

    def handle(self, *args, **opts):
        out = Path(settings.BASE_DIR) / "backups"
        out.mkdir(exist_ok=True)
        archive = out / f"backup-{datetime.now():%Y-%m-%d_%H%M}.zip"
        db = settings.DATABASES["default"]
        with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as z:
            if db["ENGINE"].endswith("sqlite3"):
                tmp = out / "tmp.sqlite3"
                src, dst = sqlite3.connect(db["NAME"]), sqlite3.connect(tmp)
                with dst:
                    src.backup(dst)               # a safe copy even while the site is being used
                src.close()
                dst.close()
                z.write(tmp, "database.sqlite3")
                tmp.unlink()
            else:
                env = {**os.environ, "MYSQL_PWD": db["PASSWORD"]}
                dump = subprocess.run(
                    ["mysqldump", "--single-transaction", f"--host={db.get('HOST') or 'localhost'}", f"--user={db['USER']}", db["NAME"]],
                    check=True, capture_output=True, env=env,
                )
                z.writestr("database.sql", dump.stdout)
            root = Path(settings.PRIVATE_MEDIA_ROOT)
            for path in root.rglob("*") if root.exists() else []:
                if path.is_file():
                    z.write(path, "private_media/" + path.relative_to(root).as_posix())
        for old in sorted(out.glob("backup-*.zip"))[: -opts["keep"]]:
            old.unlink()
        self.stdout.write(f"Backup written: {archive} ({archive.stat().st_size / 1024:.0f} KB)")