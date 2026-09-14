"""Interactive first administrator setup; passwords are never echoed or printed."""
import getpass
import os
from backend import app


def main():
    os.environ['TRITON_AUTH_MODE']='local'
    app.init_db()
    with app.db() as connection:
        exists=connection.execute("SELECT 1 FROM users WHERE active=1 AND role='ADMINISTRADOR' AND password_hash<>''").fetchone()
        if exists:
            print('Ya existe un administrador con acceso. Inicia la aplicación para gestionar los usuarios.')
            return
    username=input('Usuario del primer administrador: ').strip().lower()
    password=getpass.getpass('Contraseña (mínimo 12 caracteres): ')
    if password != getpass.getpass('Repetir contraseña: '):
        raise ValueError('Las contraseñas no coinciden')
    with app.db() as connection:
        connection.execute('BEGIN IMMEDIATE')
        if connection.execute("SELECT 1 FROM users WHERE active=1 AND role='ADMINISTRADOR' AND password_hash<>''").fetchone():
            raise ValueError('Otro administrador ya completó la configuración')
        app.identity.save(connection,dict(username=username,display_name=username,role='ADMINISTRADOR',password=password),'configuracion.local',app.ROLES)
    print('Administrador creado. Inicia con: python app.py --host 127.0.0.1 --port 8000')


if __name__=='__main__':
    main()
