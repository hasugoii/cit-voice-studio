"""Single-server SaaS accounts, manual plans and transactional character quotas."""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import secrets
import sqlite3
import threading
import time
import unicodedata
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Literal

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import FileResponse, JSONResponse, HTMLResponse, PlainTextResponse
from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRoute
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from apps import deployment, remote_access

class SafeRoute(APIRoute):
    def get_route_handler(self):
        original = super().get_route_handler()
        async def handler(request):
            try:
                response=await original(request)
                response.headers.setdefault('Cache-Control','no-store')
                return response
            except RequestValidationError as error:
                # Pydantic includes raw input values by default (incl. passwords).
                detail=[{k:e[k] for k in ('loc','msg','type')} for e in error.errors()]
                return JSONResponse({'detail':detail},status_code=422)
        return handler


router = APIRouter(prefix='/saas', include_in_schema=False, route_class=SafeRoute)
COOKIE = '__Secure-cit_saas'
SESSION_SECONDS = 7 * 86400
ADMIN_COOKIE = '__Secure-cit_admin'
ADMIN_SESSION_SECONDS = 12 * 3600
# Filled by web_stream without network round trips or access to owner history.
generate_audio: Callable | None = None
list_voices: Callable | None = None
model_health: Callable | None = None
_init_lock = threading.Lock()


def db_path() -> Path:
    return Path(os.environ.get('CIT_SAAS_DB') or (Path(os.getenv('LOCALAPPDATA') or Path.home())/'CitVoiceStudio'/'saas.sqlite3'))


@contextmanager
def connect():
    path = db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=10, isolation_level=None)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA foreign_keys=ON')
    db.execute('PRAGMA busy_timeout=10000')
    try:
        yield db
    finally:
        db.close()


def init_db():
    with _init_lock, connect() as db:
        db.execute('PRAGMA journal_mode=WAL')
        db.executescript('''
        CREATE TABLE IF NOT EXISTS plans (
          id TEXT PRIMARY KEY, name TEXT NOT NULL, char_limit INTEGER NOT NULL,
          job_max_chars INTEGER NOT NULL, max_api_keys INTEGER NOT NULL DEFAULT 2,
          enabled INTEGER NOT NULL DEFAULT 0, is_draft INTEGER NOT NULL DEFAULT 1,
          price_minor INTEGER, currency TEXT NOT NULL DEFAULT 'JPY', display_price TEXT NOT NULL DEFAULT '',
          created_at REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS users (
          id TEXT PRIMARY KEY, email TEXT UNIQUE NOT NULL, name TEXT NOT NULL,
          password_hash TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'active',
          plan_id TEXT NOT NULL REFERENCES plans(id), plan_expires_at REAL,
          created_at REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS sessions (
          token_hash TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id),
          csrf TEXT NOT NULL, expires_at REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS api_keys (
          id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id),
          name TEXT NOT NULL, prefix TEXT NOT NULL, key_hash TEXT UNIQUE NOT NULL, created_at REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS usage_jobs (
          id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id),
          period TEXT NOT NULL, characters INTEGER NOT NULL, status TEXT NOT NULL,
          created_at REAL NOT NULL, finished_at REAL, error TEXT);
        CREATE INDEX IF NOT EXISTS usage_user_period ON usage_jobs(user_id,period,status);
        CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY,value TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS auth_attempts (bucket TEXT NOT NULL, at REAL NOT NULL);
        CREATE INDEX IF NOT EXISTS auth_bucket_time ON auth_attempts(bucket,at);
        CREATE TABLE IF NOT EXISTS audit_events (id TEXT PRIMARY KEY, action TEXT NOT NULL, target_id TEXT, created_at REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS admin_users (
          id TEXT PRIMARY KEY, username TEXT UNIQUE NOT NULL, name TEXT NOT NULL,
          password_hash TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'active', created_at REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS admin_sessions (
          token_hash TEXT PRIMARY KEY, admin_id TEXT NOT NULL REFERENCES admin_users(id),
          csrf TEXT NOT NULL, expires_at REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS access_requests (
          id TEXT PRIMARY KEY, name TEXT NOT NULL, email TEXT NOT NULL,
          purpose TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'new', created_at REAL NOT NULL);
        CREATE INDEX IF NOT EXISTS access_email_time ON access_requests(email,created_at);
        ''')
        for pid,name,limit,job,price in [('trial','Trial',1000,500,0),('pro','Pro',100000,5000,None),('business','Business',500000,10000,None)]:
            db.execute('INSERT OR IGNORE INTO plans VALUES (?,?,?,?,?,0,1,?,?,?,?)',
                       (pid,name,limit,job,2,price,'JPY','',time.time()))
        db.execute('INSERT OR IGNORE INTO settings VALUES (?,?)',('registration_enabled','false'))
    try:
        db_path().chmod(0o600)
    except OSError:
        pass


def _ready():
    if not deployment.is_selfhost():
        raise HTTPException(404,'SaaS chỉ bật trong chế độ self-host.')
    init_db()


def _origin(request: Request):
    origin = request.headers.get('origin')
    if origin and origin != deployment.public_url():
        raise HTTPException(403,'Nguồn yêu cầu không được phép.')


def _admin(request: Request):
    _ready()
    _origin(request)
    token=request.cookies.get(ADMIN_COOKIE,'')
    with connect() as db:
        row=db.execute('''SELECT a.id,a.username,a.name,a.status,s.csrf FROM admin_users a
            JOIN admin_sessions s ON s.admin_id=a.id
            WHERE s.token_hash=? AND s.expires_at>? AND a.status='active' ''',
            (hashlib.sha256(token.encode()).hexdigest(),time.time())).fetchone()
    if row is None:
        raise HTTPException(401,'Vui lòng đăng nhập tài khoản quản trị.')
    if request.method not in ('GET','HEAD') and not hmac.compare_digest(request.headers.get('x-csrf-token',''),row['csrf']):
        raise HTTPException(403,'Phiên quản trị thiếu mã CSRF. Tải lại trang rồi thử lại.')
    return dict(row)


def _audit(db, action, target):
    db.execute('INSERT INTO audit_events VALUES (?,?,?,?)',(uuid.uuid4().hex,action,target,time.time()))


def _email(value):
    value = value.strip().lower()
    if len(value)>254 or not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+',value):
        raise HTTPException(422,'Địa chỉ email không hợp lệ.')
    return value


def _password_hash(password):
    if len(password)<12 or len(password)>256:
        raise HTTPException(422,'Mật khẩu cần từ 12 đến 256 ký tự.')
    salt=secrets.token_bytes(16)
    digest=hashlib.scrypt(password.encode(),salt=salt,n=16384,r=8,p=1).hex()
    return salt.hex()+':'+digest


def _password_ok(password, stored):
    try:
        salt,digest=stored.split(':')
        actual=hashlib.scrypt(password.encode(),salt=bytes.fromhex(salt),n=16384,r=8,p=1).hex()
        return hmac.compare_digest(actual,digest)
    except (ValueError,TypeError):
        return False


def bootstrap_admin(username,password,name='Quản trị viên'):
    """First owner provisioning is CLI-only. Never resets an existing account."""
    _ready()
    username=username.strip().lower()
    if not re.fullmatch(r'[a-z0-9][a-z0-9_.@-]{2,79}',username):
        raise HTTPException(422,'Tên đăng nhập cần 3–80 ký tự chữ, số hoặc . _ @ -')
    password_hash=_password_hash(password)
    with connect() as db:
        db.execute('BEGIN IMMEDIATE')
        if db.execute('SELECT COUNT(*) FROM admin_users').fetchone()[0]:
            raise HTTPException(409,'Đã có tài khoản admin. Không ghi đè thông tin đăng nhập.')
        aid=uuid.uuid4().hex
        db.execute('INSERT INTO admin_users VALUES (?,?,?,?,?,?)',(aid,username,name,password_hash,'active',time.time()))
        _audit(db,'admin.bootstrap',aid);db.commit()
    return {'id':aid,'username':username,'name':name,'status':'active'}


class AdminLogin(BaseModel):
    username:str=Field(min_length=1,max_length=80)
    password:str=Field(min_length=1,max_length=256)


def _admin_result(row):
    return {'admin':{k:row[k] for k in ('id','username','name','status')},'session_csrf':row['csrf']}


@router.post('/api/admin-auth/login')
def admin_login(data:AdminLogin,request:Request,response:Response):
    _ready();_origin(request)
    username=data.username.strip().lower()
    _rate(request,'admin:'+username)
    with connect() as db:
        row=db.execute('SELECT * FROM admin_users WHERE username=?',(username,)).fetchone()
    stored=row['password_hash'] if row else '00'*16+':'+'00'*64
    if not _password_ok(data.password,stored) or not row or row['status']!='active':
        raise HTTPException(401,'Tên đăng nhập hoặc mật khẩu không đúng.')
    token=secrets.token_urlsafe(32);csrf=secrets.token_urlsafe(24)
    with connect() as db:
        db.execute('BEGIN IMMEDIATE')
        fresh=db.execute('SELECT password_hash,status FROM admin_users WHERE id=?',(row['id'],)).fetchone()
        if not fresh or fresh['status']!='active' or not hmac.compare_digest(fresh['password_hash'],stored):
            raise HTTPException(401,'Thông tin đăng nhập vừa thay đổi. Vui lòng đăng nhập lại.')
        db.execute('DELETE FROM admin_sessions WHERE expires_at<?',(time.time(),))
        db.execute('INSERT INTO admin_sessions VALUES (?,?,?,?)',(hashlib.sha256(token.encode()).hexdigest(),row['id'],csrf,time.time()+ADMIN_SESSION_SECONDS))
        _audit(db,'admin.login',row['id'])
        db.commit()
    response.set_cookie(ADMIN_COOKIE,token,max_age=ADMIN_SESSION_SECONDS,secure=True,httponly=True,samesite='strict',path='/')
    response.headers['Cache-Control']='no-store'
    return _admin_result({**dict(row),'csrf':csrf})


@router.get('/api/admin-auth/me')
def admin_me(request:Request,response:Response):
    response.headers['Cache-Control']='no-store'
    return _admin_result(_admin(request))


@router.get('/api/admin-auth/check')
def admin_check(request:Request):
    _admin(request)
    return Response(status_code=204,headers={'Cache-Control':'no-store'})


@router.post('/api/admin-auth/logout')
def admin_logout(request:Request,response:Response):
    admin=_admin(request)
    with connect() as db:
        db.execute('DELETE FROM admin_sessions WHERE token_hash=?',(hashlib.sha256(request.cookies.get(ADMIN_COOKIE,'').encode()).hexdigest(),))
        _audit(db,'admin.logout',admin['id'])
    response.delete_cookie(ADMIN_COOKIE,path='/',secure=True,httponly=True,samesite='strict')
    response.headers['Cache-Control']='no-store'
    return {'ok':True}


class AdminPassword(BaseModel):
    current_password:str=Field(min_length=1,max_length=256)
    new_password:str=Field(min_length=12,max_length=256)


@router.post('/api/admin-auth/password')
def admin_change_password(data:AdminPassword,request:Request,response:Response):
    admin=_admin(request)
    _rate(request,'admin-password:'+admin['username'])
    with connect() as db:
        row=db.execute('SELECT password_hash FROM admin_users WHERE id=?',(admin['id'],)).fetchone()
        if not _password_ok(data.current_password,row['password_hash']):
            raise HTTPException(401,'Mật khẩu hiện tại không đúng.')
        new_hash=_password_hash(data.new_password)
        db.execute('BEGIN IMMEDIATE')
        fresh=db.execute('SELECT password_hash FROM admin_users WHERE id=?',(admin['id'],)).fetchone()
        if not fresh or not hmac.compare_digest(fresh['password_hash'],row['password_hash']):
            raise HTTPException(409,'Mật khẩu vừa thay đổi ở phiên khác. Vui lòng đăng nhập lại.')
        db.execute('UPDATE admin_users SET password_hash=? WHERE id=?',(new_hash,admin['id']))
        db.execute('DELETE FROM admin_sessions WHERE admin_id=?',(admin['id'],))
        _audit(db,'admin.password_change',admin['id']);db.commit()
    response.delete_cookie(ADMIN_COOKIE,path='/',secure=True,httponly=True,samesite='strict')
    return {'ok':True,'login_required':True}


def _public_user(row):
    return {k:row[k] for k in ('id','email','name','status','plan_id','plan_expires_at','created_at')}


def _plan(row):
    d=dict(row)
    d['enabled']=bool(d['enabled']);d['is_draft']=bool(d['is_draft'])
    return d


def _valid_plan(db,pid):
    row=db.execute('SELECT * FROM plans WHERE id=?',(pid,)).fetchone()
    if not row or not row['enabled'] or row['is_draft']:
        raise HTTPException(403,'Gói chưa kích hoạt. Liên hệ quản trị viên để được gán gói.')
    return row


def _active(row):
    if row['status']!='active':
        raise HTTPException(403,'Tài khoản đang bị tạm khóa.')
    if row['plan_expires_at'] is not None and row['plan_expires_at']<=time.time():
        raise HTTPException(403,'Gói đã hết hạn. Liên hệ quản trị viên.')


def _identity(request, mutate=False):
    _ready();_origin(request)
    key=request.headers.get('x-api-key','')
    auth=request.headers.get('authorization','')
    if not key and auth.lower().startswith('bearer '):key=auth[7:].strip()
    with connect() as db:
        csrf=None
        if key:
            row=db.execute('SELECT u.* FROM users u JOIN api_keys k ON k.user_id=u.id WHERE k.key_hash=?',
                           (hashlib.sha256(key.encode()).hexdigest(),)).fetchone()
        else:
            token=request.cookies.get(COOKIE,'')
            session=db.execute('SELECT * FROM sessions WHERE token_hash=? AND expires_at>?',
                               (hashlib.sha256(token.encode()).hexdigest(),time.time())).fetchone()
            row=db.execute('SELECT * FROM users WHERE id=?',(session['user_id'],)).fetchone() if session else None
            if session:
                csrf=session['csrf']
                if mutate and not hmac.compare_digest(request.headers.get('x-csrf-token',''),csrf):
                    raise HTTPException(403,'Phiên làm việc thiếu mã CSRF. Tải lại trang rồi thử lại.')
        if row is None:raise HTTPException(401,'Cần đăng nhập hoặc cung cấp khóa API hợp lệ.')
        _active(row)
        return dict(row),csrf


def _period():
    return datetime.now(timezone(timedelta(hours=9))).strftime('%Y-%m')


def usage(db,uid,plan):
    counts=db.execute("SELECT COALESCE(SUM(CASE WHEN status='succeeded' THEN characters ELSE 0 END),0),COALESCE(SUM(CASE WHEN status='reserved' THEN characters ELSE 0 END),0) FROM usage_jobs WHERE user_id=? AND period=?",(uid,_period())).fetchone()
    return {'used':counts[0],'reserved':counts[1],'limit':plan['char_limit'],
            'remaining':max(0,plan['char_limit']-counts[0]-counts[1]),'period':_period(),'timezone':'Asia/Tokyo'}


def _session(user,response):
    token=secrets.token_urlsafe(32);csrf=secrets.token_urlsafe(24)
    with connect() as db:
        db.execute('DELETE FROM sessions WHERE expires_at<?',(time.time(),))
        db.execute('INSERT INTO sessions VALUES (?,?,?,?)',(hashlib.sha256(token.encode()).hexdigest(),user['id'],csrf,time.time()+SESSION_SECONDS))
    response.set_cookie(COOKIE,token,max_age=SESSION_SECONDS,secure=True,httponly=True,samesite='strict',path='/saas')
    return {'user':_public_user(user),'session_csrf':csrf}


def _rate(request,email,scope=''):
    peer=request.client.host if request.client else 'unknown'
    buckets=[scope+'login:'+email,scope+'peer:'+peer]
    now=time.time()
    with connect() as db:
        db.execute('BEGIN IMMEDIATE')
        db.execute('DELETE FROM auth_attempts WHERE at<?',(now-900,))
        for bucket,limit in zip(buckets,(8,60)):
            if db.execute('SELECT COUNT(*) FROM auth_attempts WHERE bucket=?',(bucket,)).fetchone()[0]>=limit:
                db.rollback();raise HTTPException(429,'Bạn đã gửi nhiều yêu cầu. Vui lòng chờ 15 phút.' if scope else 'Thử đăng nhập quá nhiều lần. Vui lòng chờ 15 phút.')
        db.executemany('INSERT INTO auth_attempts VALUES (?,?)',[(b,now) for b in buckets]);db.commit()


class Account(BaseModel):
    email: str=Field(max_length=254)
    password: str=Field(min_length=12,max_length=256)
    name: str=Field(default='',max_length=100)


class AccessRequestInput(BaseModel):
    name:str=Field(min_length=1,max_length=100)
    email:str=Field(min_length=3,max_length=254)
    purpose:str=Field(default='',max_length=1000)
    website:str=Field(default='',max_length=200)


@router.post('/api/access-requests')
def request_access(data:AccessRequestInput,request:Request):
    _ready();_origin(request)
    message={'ok':True,'message':'Đã ghi nhận yêu cầu. Quản trị viên sẽ xem nhu cầu và thông tin liên hệ của bạn.'}
    if data.website.strip():return message
    email=_email(data.email)
    name=data.name.strip()
    if not name:raise HTTPException(422,'Vui lòng nhập tên của bạn.')
    _rate(request,email,scope='access:')
    with connect() as db:
        db.execute('BEGIN IMMEDIATE')
        if not db.execute('SELECT 1 FROM access_requests WHERE email=? AND created_at>?',(email,time.time()-86400)).fetchone():
            db.execute('INSERT INTO access_requests VALUES (?,?,?,?,?,?)',(uuid.uuid4().hex,name,email,data.purpose.strip(),'new',time.time()))
        db.commit()
    return message


@router.get('/api/admin/access-requests')
def admin_access_requests(request:Request):
    _admin(request)
    with connect() as db:
        return {'items':[dict(row) for row in db.execute('SELECT * FROM access_requests ORDER BY created_at DESC LIMIT 500')]}


class AccessRequestPatch(BaseModel):
    status:Literal['new','reviewed','closed']


@router.patch('/api/admin/access-requests/{rid}')
def update_access_request(rid:str,data:AccessRequestPatch,request:Request):
    _admin(request)
    with connect() as db:
        if db.execute('UPDATE access_requests SET status=? WHERE id=?',(data.status,rid)).rowcount!=1:
            raise HTTPException(404,'Không tìm thấy yêu cầu.')
        _audit(db,'access_request.'+data.status,rid)
    return {'ok':True,'status':data.status}


@router.get('/homepage')
def homepage():
    if not deployment.is_selfhost():raise HTTPException(404)
    from html import escape
    page=Path(__file__).with_name('landing_static')/'homepage.html'
    return HTMLResponse(page.read_text(encoding='utf-8').replace('__PUBLIC_URL__',escape(deployment.public_url(),quote=True)),
                        headers={'Cache-Control':'public, max-age=300'})


@router.get('/landing-assets/{name}')
def landing_assets(name:str):
    if not deployment.is_selfhost():raise HTTPException(404)
    allowed={'homepage.css','homepage.js','demo-male.wav','demo-female.wav','favicon.svg',
             'font-latin.woff2','font-vietnamese.woff2'}
    if name not in allowed:raise HTTPException(404)
    path=Path(__file__).with_name('landing_static')/name
    if not path.is_file():raise HTTPException(404)
    return FileResponse(path,headers={'Cache-Control':'public, max-age=3600'})


@router.get('/robots.txt')
def robots():
    if not deployment.is_selfhost():raise HTTPException(404)
    return PlainTextResponse('User-agent: *\nAllow: /\nDisallow: /studio\nDisallow: /api/\nDisallow: /saas/admin\nDisallow: /saas/api/\nSitemap: '+deployment.public_url()+'/sitemap.xml\n')


@router.get('/sitemap.xml')
def sitemap():
    if not deployment.is_selfhost():raise HTTPException(404)
    from xml.sax.saxutils import escape
    return Response('<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"><url><loc>'+escape(deployment.public_url())+'/</loc></url></urlset>',media_type='application/xml')


@router.get('/api/config')
def config():
    _ready()
    with connect() as db: enabled=json.loads(db.execute("SELECT value FROM settings WHERE key='registration_enabled'").fetchone()[0])
    return {'billing_mode':'manual','currency':'JPY','registration_enabled':enabled,'user_api_url':deployment.public_url()+'/saas/api'}


@router.post('/api/register',status_code=201)
def register(data:Account,request:Request,response:Response):
    _ready();_origin(request)
    email=_email(data.email);_rate(request,email)
    with connect() as db:
        if not json.loads(db.execute("SELECT value FROM settings WHERE key='registration_enabled'").fetchone()[0]):
            raise HTTPException(403,'Đăng ký đang đóng. Liên hệ quản trị viên để được cấp tài khoản.')
    user=_create_user(data,'trial','active')
    return _session(user,response)


@router.post('/api/login')
def login(data:Account,request:Request,response:Response):
    _ready();_origin(request)
    email=_email(data.email);_rate(request,email)
    with connect() as db:row=db.execute('SELECT * FROM users WHERE email=?',(email,)).fetchone()
    # Perform same work for missing accounts to reduce email enumeration timing.
    stored=row['password_hash'] if row else '00'*16+':'+'00'*64
    if not _password_ok(data.password,stored):raise HTTPException(401,'Email hoặc mật khẩu không đúng.')
    _active(row)
    with connect() as db:_valid_plan(db,row['plan_id'])
    return _session(row,response)


@router.post('/api/logout')
def logout(request:Request,response:Response):
    _identity(request,True)
    with connect() as db:db.execute('DELETE FROM sessions WHERE token_hash=?',(hashlib.sha256(request.cookies.get(COOKIE,'').encode()).hexdigest(),))
    response.delete_cookie(COOKIE,path='/saas',secure=True,httponly=True,samesite='strict')
    return {'ok':True}


@router.get('/api/me')
def me(request:Request):
    user,csrf=_identity(request)
    with connect() as db:
        plan=_valid_plan(db,user['plan_id'])
        keys=[dict(r) for r in db.execute('SELECT id,name,prefix,created_at FROM api_keys WHERE user_id=? ORDER BY created_at DESC',(user['id'],))]
        return {'user':_public_user(user),'plan':_plan(plan),'usage':usage(db,user['id'],plan),'api_keys':keys,'session_csrf':csrf}


class KeyName(BaseModel):
    name:str=Field(default='API',min_length=1,max_length=80)


@router.post('/api/keys',status_code=201)
def create_key(data:KeyName,request:Request):
    user,_=_identity(request,True)
    with connect() as db:
        db.execute('BEGIN IMMEDIATE');plan=_valid_plan(db,user['plan_id'])
        if db.execute('SELECT COUNT(*) FROM api_keys WHERE user_id=?',(user['id'],)).fetchone()[0]>=plan['max_api_keys']:
            raise HTTPException(409,'Đã đạt số khóa API tối đa của gói. Thu hồi khóa cũ trước.')
        token='sv_'+secrets.token_urlsafe(32);kid=uuid.uuid4().hex;created=time.time()
        db.execute('INSERT INTO api_keys VALUES (?,?,?,?,?,?)',(kid,user['id'],data.name,token[:10],hashlib.sha256(token.encode()).hexdigest(),created));db.commit()
    return {'api_key':token,'key':{'id':kid,'name':data.name,'prefix':token[:10],'created_at':created}}


@router.delete('/api/keys/{kid}')
def delete_key(kid:str,request:Request):
    user,_=_identity(request,True)
    with connect() as db:
        if db.execute('DELETE FROM api_keys WHERE id=? AND user_id=?',(kid,user['id'])).rowcount!=1:raise HTTPException(404,'Không tìm thấy khóa.')
    return {'ok':True}


@router.get('/api/usage')
def ledger(request:Request):
    user,_=_identity(request)
    with connect() as db:
        rows=db.execute('SELECT id,status,characters,created_at,error FROM usage_jobs WHERE user_id=? ORDER BY created_at DESC LIMIT 100',(user['id'],))
        return {'items':[dict(r) for r in rows]}


def reserve(uid,text):
    characters=len(unicodedata.normalize('NFC',text.strip()))
    with connect() as db:
        db.execute('BEGIN IMMEDIATE')
        user=db.execute('SELECT * FROM users WHERE id=?',(uid,)).fetchone();_active(user)
        plan=_valid_plan(db,user['plan_id'])
        if not characters or characters>plan['job_max_chars']:raise HTTPException(422,f"Mỗi yêu cầu cần từ 1 đến {plan['job_max_chars']} ký tự.")
        if usage(db,uid,plan)['remaining']<characters:raise HTTPException(402,'Đã hết hạn mức ký tự trong tháng. Liên hệ quản trị viên để nâng gói.')
        if db.execute("SELECT COUNT(*) FROM usage_jobs WHERE status='reserved'").fetchone()[0]:raise HTTPException(429,'Máy chủ đang tạo giọng. Vui lòng thử lại sau.')
        jid=uuid.uuid4().hex
        db.execute("INSERT INTO usage_jobs VALUES (?,?,?,?, 'reserved',?,NULL,NULL)",(jid,uid,_period(),characters,time.time()));db.commit()
        return jid


def finish(jid,success,error=None):
    with connect() as db:
        db.execute("UPDATE usage_jobs SET status=?,finished_at=?,error=? WHERE id=? AND status='reserved'",('succeeded' if success else 'failed',time.time(),error,jid))


class TtsRequest(BaseModel):
    text:str=Field(min_length=1,max_length=20000)
    voice_id:str|None=Field(default=None,max_length=100)
    language:str|None=Field(default=None,max_length=10)
    format:Literal['wav']='wav'


@router.get('/api/voices')
async def voices(request:Request):
    _identity(request)
    if list_voices is None:raise HTTPException(503,'Mô hình chưa sẵn sàng.')
    return await run_in_threadpool(lambda:[v for v in list_voices() if not v.get('isCloned')])


@router.get('/api/health')
async def health(request:Request):
    _identity(request)
    return await run_in_threadpool(model_health) if model_health else {'status':'loading'}


@router.post('/api/tts/generate')
async def generate(data:TtsRequest,request:Request):
    user,_=_identity(request,True)
    if generate_audio is None or list_voices is None:raise HTTPException(503,'Mô hình chưa sẵn sàng.')
    allowed=await run_in_threadpool(lambda:[v['id'] for v in list_voices() if not v.get('isCloned')])
    if data.voice_id not in allowed:raise HTTPException(422,'Chọn một giọng công khai trong /saas/api/voices.')
    jid=reserve(user['id'],data.text)
    try:
        response=await run_in_threadpool(generate_audio,data.model_dump())
        if response.status_code>=400:
            finish(jid,False,'Không tạo được âm thanh.');return response
        finish(jid,True)
        response.headers['X-Usage-Job']=jid
        response.headers['Cache-Control']='no-store'
        return response
    except BaseException as error:
        finish(jid,False,'Tạo giọng thất bại; đã hoàn hạn mức.')
        if isinstance(error,HTTPException):raise
        if isinstance(error,Exception):raise HTTPException(503,'Tạo giọng thất bại. Hạn mức chưa bị trừ, vui lòng thử lại.') from error
        raise


def recover_jobs():
    """Called once before app serves traffic, never during a request."""
    if deployment.is_selfhost():
        init_db()
        with connect() as db:db.execute("UPDATE usage_jobs SET status='failed',finished_at=?,error='Máy chủ đã khởi động lại; hoàn hạn mức.' WHERE status='reserved'",(time.time(),))


class AdminAccount(Account):
    plan_id:str='trial'
    status:Literal['active','suspended']='active'


def _create_user(data,plan_id,status):
    email=_email(data.email);password_hash=_password_hash(data.password);uid=uuid.uuid4().hex
    with connect() as db:
        _valid_plan(db,plan_id)
        try:db.execute('INSERT INTO users VALUES (?,?,?,?,?,?,NULL,?)',(uid,email,data.name.strip() or email,password_hash,status,plan_id,time.time()))
        except sqlite3.IntegrityError:raise HTTPException(409,'Không tạo được tài khoản. Kiểm tra lại email.')
        _audit(db,'user.create',uid)
        return db.execute('SELECT * FROM users WHERE id=?',(uid,)).fetchone()


@router.post('/api/admin/users',status_code=201)
def admin_create_user(data:AdminAccount,request:Request):
    _admin(request)
    return {'user':_public_user(_create_user(data,data.plan_id,data.status))}


@router.get('/api/admin/users')
def admin_users(request:Request):
    _admin(request)
    with connect() as db:
        rows=db.execute("SELECT u.*,COALESCE((SELECT SUM(characters) FROM usage_jobs j WHERE j.user_id=u.id AND j.period=? AND j.status='succeeded'),0) AS used_characters FROM users u ORDER BY created_at DESC LIMIT 1000",(_period(),))
        return {'items':[{**_public_user(r),'used_characters':r['used_characters']} for r in rows]}


class UserPatch(BaseModel):
    status:Literal['active','suspended']|None=None
    plan_id:str|None=None
    plan_expires_at:datetime|None=None


@router.patch('/api/admin/users/{uid}')
def admin_patch_user(uid:str,data:UserPatch,request:Request):
    _admin(request)
    with connect() as db:
        db.execute('BEGIN IMMEDIATE')
        if not db.execute('SELECT 1 FROM users WHERE id=?',(uid,)).fetchone():raise HTTPException(404,'Không tìm thấy tài khoản.')
        changes={k:v for k,v in data.model_dump(exclude_unset=True).items() if k!='plan_expires_at' and v is not None}
        if 'plan_id' in changes:_valid_plan(db,changes['plan_id'])
        if 'plan_expires_at' in data.model_fields_set:
            expiry=data.plan_expires_at
            if expiry and expiry.tzinfo is None:raise HTTPException(422,'Thời hạn phải có múi giờ.')
            changes['plan_expires_at']=expiry.timestamp() if expiry else None
        for k,v in changes.items():db.execute(f'UPDATE users SET {k}=? WHERE id=?',(v,uid))
        _audit(db,'user.update',uid);db.commit()
        return {'user':_public_user(db.execute('SELECT * FROM users WHERE id=?',(uid,)).fetchone())}


class PlanInput(BaseModel):
    id:str=Field(pattern=r'^[a-z0-9_-]{1,40}$')
    name:str=Field(min_length=1,max_length=100)
    char_limit:int=Field(ge=0,le=100000000)
    job_max_chars:int=Field(ge=1,le=20000)
    max_api_keys:int=Field(default=2,ge=1,le=20)
    enabled:bool=False
    is_draft:bool=True
    price_minor:int|None=Field(default=None,ge=0,le=1000000000)
    currency:str=Field(default='JPY',pattern=r'^[A-Z]{3}$')
    display_price:str=Field(default='',max_length=100)


class PlanPatch(BaseModel):
    name:str|None=Field(default=None,min_length=1,max_length=100)
    char_limit:int|None=Field(default=None,ge=0,le=100000000)
    job_max_chars:int|None=Field(default=None,ge=1,le=20000)
    max_api_keys:int|None=Field(default=None,ge=1,le=20)
    enabled:bool|None=None
    is_draft:bool|None=None
    price_minor:int|None=Field(default=None,ge=0,le=1000000000)
    currency:str|None=Field(default=None,pattern=r'^[A-Z]{3}$')
    display_price:str|None=Field(default=None,max_length=100)


def _validate_plan(values):
    if values['enabled'] and (values['is_draft'] or values['price_minor'] is None or values['char_limit']<=0):
        raise HTTPException(422,'Trước khi kích hoạt: bỏ trạng thái nháp, đặt giá (0 nếu miễn phí) và hạn mức lớn hơn 0.')
    if values['job_max_chars']>values['char_limit'] and values['enabled']:
        raise HTTPException(422,'Hạn mức mỗi yêu cầu không được vượt hạn mức tháng.')


@router.get('/api/admin/plans')
def admin_plans(request:Request):
    _admin(request)
    with connect() as db:return {'items':[_plan(r) for r in db.execute('SELECT * FROM plans ORDER BY created_at,id')]}


@router.post('/api/admin/plans',status_code=201)
def admin_add_plan(data:PlanInput,request:Request):
    _admin(request);values=data.model_dump();_validate_plan(values)
    with connect() as db:
        try:db.execute('INSERT INTO plans VALUES (?,?,?,?,?,?,?,?,?,?,?)',tuple(values[k] for k in ['id','name','char_limit','job_max_chars','max_api_keys','enabled','is_draft','price_minor','currency','display_price'])+(time.time(),))
        except sqlite3.IntegrityError:raise HTTPException(409,'Mã gói đã tồn tại.')
        _audit(db,'plan.create',data.id)
    return {'plan':values}


@router.patch('/api/admin/plans/{pid}')
def admin_update_plan(pid:str,data:PlanPatch,request:Request):
    _admin(request)
    with connect() as db:
        db.execute('BEGIN IMMEDIATE')
        row=db.execute('SELECT * FROM plans WHERE id=?',(pid,)).fetchone()
        if row is None:raise HTTPException(404,'Không tìm thấy gói.')
        changes=data.model_dump(exclude_unset=True)
        if any(v is None and k!='price_minor' for k,v in changes.items()):raise HTTPException(422,'Thông số gói không được để trống.')
        values={**dict(row),**changes};_validate_plan(values)
        for k,v in changes.items():db.execute(f'UPDATE plans SET {k}=? WHERE id=?',(v,pid))
        _audit(db,'plan.update',pid);db.commit()
    return {'plan':_plan(values)}


@router.get('/api/admin/overview')
def admin_overview(request:Request):
    _admin(request)
    with connect() as db:
        return {'users_count':db.execute('SELECT COUNT(*) FROM users').fetchone()[0],
                'active_users':db.execute("SELECT COUNT(*) FROM users WHERE status='active'").fetchone()[0],
                'used_characters':db.execute("SELECT COALESCE(SUM(characters),0) FROM usage_jobs WHERE status='succeeded' AND period=?",(_period(),)).fetchone()[0],
                'jobs_count':db.execute("SELECT COUNT(*) FROM usage_jobs WHERE status='succeeded' AND period=?",(_period(),)).fetchone()[0],
                'billing_mode':'manual'}


class SettingsPatch(BaseModel):
    registration_enabled:bool


@router.get('/api/admin/settings')
def admin_settings(request:Request):
    _admin(request);return config()


@router.patch('/api/admin/settings')
def admin_update_settings(data:SettingsPatch,request:Request):
    _admin(request)
    with connect() as db:
        if data.registration_enabled:_valid_plan(db,'trial')
        db.execute("UPDATE settings SET value=? WHERE key='registration_enabled'",(json.dumps(data.registration_enabled),))
        _audit(db,'registration.update',None)
    return config()


@router.get('')
@router.get('/')
def user_page():
    _ready()
    return FileResponse(Path(__file__).with_name('saas_static')/'index.html',headers={'Cache-Control':'no-store'})


@router.get('/admin')
@router.get('/admin/')
def admin_page(request:Request):
    try:
        _admin(request)
    except HTTPException as error:
        if error.status_code!=401:raise
        from fastapi.responses import RedirectResponse
        return RedirectResponse('/saas/admin/login',status_code=303)
    return FileResponse(Path(__file__).with_name('saas_static')/'admin.html',headers={'Cache-Control':'no-store'})


@router.get('/admin/login')
def admin_login_page():
    _ready()
    return FileResponse(Path(__file__).with_name('saas_static')/'admin.html',headers={'Cache-Control':'no-store'})


@router.get('/assets/{name}')
def assets(name:str):
    _ready()
    if name not in {'app.css','app.js','admin.js','common.js','style.css'}:raise HTTPException(404)
    return FileResponse(Path(__file__).with_name('saas_static')/name,headers={'Cache-Control':'no-cache'})
