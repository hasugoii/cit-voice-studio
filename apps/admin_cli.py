"""Provision first administrator from a trusted VPS terminal, never over HTTP."""
import argparse
import getpass
import json
import sys

from fastapi import HTTPException
from apps import saas


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('command',choices=['bootstrap','reset-password'])
    parser.add_argument('--username',default='admin')
    parser.add_argument('--name',default='Quản trị viên')
    parser.add_argument('--stdin-json',action='store_true',help='Read secrets from stdin, never command arguments')
    args=parser.parse_args()
    if args.stdin_json:
        data=json.load(sys.stdin)
        username=data.get('username',args.username)
        password=data['password']
    else:
        username=args.username
        password=getpass.getpass('Mật khẩu admin (ít nhất 12 ký tự): ')
        if password!=getpass.getpass('Nhập lại mật khẩu: '):
            raise SystemExit('Mật khẩu nhập lại không khớp.')
    try:
        if args.command=='bootstrap':
            admin=saas.bootstrap_admin(username,password,args.name)
        else:
            saas._ready()
            new_hash=saas._password_hash(password)
            with saas.connect() as db:
                db.execute('BEGIN IMMEDIATE')
                row=db.execute('SELECT id,username FROM admin_users WHERE username=?',(username.strip().lower(),)).fetchone()
                if row is None:raise HTTPException(404,'Không tìm thấy admin.')
                db.execute('UPDATE admin_users SET password_hash=? WHERE id=?',(new_hash,row['id']))
                db.execute('DELETE FROM admin_sessions WHERE admin_id=?',(row['id'],))
                saas._audit(db,'admin.password_reset_cli',row['id']);db.commit()
                admin=dict(row)
    except HTTPException as error:
        raise SystemExit(error.detail)
    print('Đã tạo admin:' if args.command=='bootstrap' else 'Đã đặt lại mật khẩu và thu hồi phiên:',admin['username'])


if __name__=='__main__':main()
