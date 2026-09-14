import sqlite3
import tempfile
import unittest
import uuid
from contextlib import closing
from datetime import datetime, time
from pathlib import Path
from unittest.mock import patch
from backend import app
from backend.maintenance import restore_backup
from backend.services import identity
from tests.test_local_identity import LocalIdentityTest


class DateAndRestoreTest(unittest.TestCase):
    def test_creation_priority_and_hour(self):
        values = {'source_creation_date': datetime(2026,9,1),
                  'source_order_date': datetime(2026,9,2), 'source_order_time':1601}
        self.assertEqual(app.source_order_timestamp(values.get),'2026-09-01 16:01:00')
        values['source_order_time']=time(15,59)
        self.assertEqual(app.source_order_timestamp(values.get),'2026-09-01 15:59:00')
        values['source_order_time']=None
        self.assertEqual(app.source_order_timestamp(values.get),'2026-09-01')

    def test_restore_quarantines_outbox(self):
        directory=app.ROOT/'qa'/'runtime'/('restore-'+uuid.uuid4().hex)
        directory.mkdir(parents=True)
        try:
            source=directory/'backup.db'
            with closing(sqlite3.connect(source)) as connection:
                connection.execute('CREATE TABLE reception_notifications(status TEXT,error TEXT)')
                connection.executemany('INSERT INTO reception_notifications(status) VALUES(?)',
                    [('PENDIENTE ENVIO',),('ERROR',),('ENVIANDO',),('ENVIADO',)])
                connection.commit()
            target=restore_backup(source,Path(directory)/'live.db')
            with closing(sqlite3.connect(target)) as connection:
                states=[row[0] for row in connection.execute('SELECT status FROM reception_notifications')]
                self.assertEqual(states,['REVISAR ENVIO']*3+['ENVIADO'])
        finally:
            for file in directory.iterdir():
                file.unlink()
            directory.rmdir()


class ExpirationTest(LocalIdentityTest):
    def test_expired_session_redirect_contract(self):
        cookie=self.login()
        with app.db() as connection:
            connection.execute('UPDATE user_sessions SET expires_at=0')
        self.assertEqual(self.call('/api/users',cookie=cookie)['status'],401)
        self.assertEqual(self.call('/api/users',{'username':'ignored'},cookie=cookie)['status'],401)

    def test_completed_lockout_restarts_window(self):
        with app.db() as connection:
            with patch.object(identity.time,'time',return_value=10000):
                for _ in range(5):identity.login(connection,'admin.qa','incorrect')
            with patch.object(identity.time,'time',return_value=10901):
                identity.login(connection,'admin.qa','incorrect')
            self.assertEqual(connection.execute('SELECT failures FROM login_attempts').fetchone()[0],1)


if __name__=='__main__':unittest.main()
