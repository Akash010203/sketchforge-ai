"""Optional backend renderers."""
from __future__ import annotations

from sketchforge.generation.app_specification import AppSpec
from sketchforge.generation.backend.schema_generator import _py_type, _snake


def sqlalchemy_models(spec: AppSpec) -> str:
    out = ['"""Generated SQLAlchemy models."""', 'from datetime import datetime',
           'from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column',
           'from sqlalchemy import String, Float, DateTime, func', '',
           'class Base(DeclarativeBase):', '    pass', '']
    for e in spec.entities:
        out += [f'class {e.name}(Base):', f'    __tablename__ = {_snake(e.name)!r}',
                f'    {e.primary_key}: Mapped[int] = mapped_column(primary_key=True)']
        for f in e.fields:
            number = _py_type(f.type) == 'float'
            typ = ('float' if number else 'str') + ('' if f.required else ' | None')
            out.append(f'    {f.name}: Mapped[{typ}] = mapped_column({"Float" if number else "String"}, nullable={not f.required!r})')
        if e.timestamps:
            out += ['    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())',
                    '    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())']
        out.append('')
    return '\n'.join(out)


def sqlalchemy_logic(spec: AppSpec) -> str:
    out = ['"""SQLAlchemy CRUD operations."""', 'from sqlalchemy import select',
           'from .database import SessionLocal', 'from .models import ' + ', '.join(e.name for e in spec.entities), '']
    for e in spec.entities:
        t = _snake(e.name); allowed = tuple(f.name for f in e.fields)
        out += [f'def create_{t}(data):', '    with SessionLocal() as db:',
                f'        obj = {e.name}(**{{k:v for k,v in data.items() if k in {allowed!r}}})',
                '        db.add(obj); db.commit(); db.refresh(obj); return _as_dict(obj)', '',
                f'def get_{t}(item_id):', '    with SessionLocal() as db:', f'        obj=db.get({e.name},item_id)',
                '        return _as_dict(obj) if obj else None', '',
                f'def list_{t}():', '    with SessionLocal() as db:',
                f'        rows=db.scalars(select({e.name}).order_by({e.name}.{e.primary_key}.desc())).all()',
                '        return [_as_dict(x) for x in rows]', '',
                f'def update_{t}(item_id,data):', '    with SessionLocal() as db:', f'        obj=db.get({e.name},item_id)',
                '        if not obj: return None', f'        for k,v in data.items():\n            if k in {allowed!r}: setattr(obj,k,v)',
                '        db.commit(); db.refresh(obj); return _as_dict(obj)', '',
                f'def delete_{t}(item_id):', '    with SessionLocal() as db:', f'        obj=db.get({e.name},item_id)',
                '        if not obj: return False', '        db.delete(obj); db.commit(); return True', '']
    out += ['def _as_dict(obj):', '    return {c.name:getattr(obj,c.name) for c in obj.__table__.columns}']
    return '\n'.join(out) + '\n'


def prisma_schema(spec: AppSpec) -> str:
    provider = {'sqlite':'sqlite','postgresql':'postgresql','mysql':'mysql'}[spec.database]
    url = '"file:./dev.db"' if provider == 'sqlite' else 'env("DATABASE_URL")'
    out = ['generator client {','  provider = "prisma-client-js"','}','', 'datasource db {',
           f'  provider = "{provider}"', f'  url = {url}', '}', '']
    types={'text':'String','email':'String','password':'String','number':'Float','select':'String'}
    for e in spec.entities:
        out += [f'model {e.name} {{',f'  {e.primary_key} Int @id @default(autoincrement())']
        for f in e.fields: out.append(f'  {f.name} {types.get(f.type,"String")}{"" if f.required else "?"}')
        if e.timestamps: out += ['  created_at DateTime @default(now())','  updated_at DateTime @updatedAt']
        out += ['}','']
    return '\n'.join(out)


def api_source(spec: AppSpec) -> str:
    """Generate Flask or FastAPI CRUD endpoints against existing logic functions."""
    if spec.api_target == 'graphql':
        return _graphql_api(spec)
    if spec.orm == 'prisma':
        raise ValueError('Prisma generates schema.prisma; select SQLAlchemy or dataclass for Python API targets.')
    fast = spec.api_target == 'fastapi'
    sqlalch = spec.orm == 'sqlalchemy' or spec.database != 'sqlite'
    out = (['"""FastAPI CRUD API; run uvicorn backend.api:app"""','from fastapi import FastAPI, HTTPException',
            'from typing import Any','from dataclasses import asdict, is_dataclass','from . import logic',
            'from .database import initialise',
            ('from .models import '+', '.join(e.name for e in spec.entities)) if spec.entities else 'from . import models', 'app=FastAPI()', 'initialise()',
            'from fastapi.middleware.cors import CORSMiddleware',
            'app.add_middleware(CORSMiddleware,allow_origins=__import__("os").environ.get("CORS_ORIGINS","*").split(","),allow_methods=["*"] ,allow_headers=["*"])',
            'def _data(x): return x if isinstance(x,dict) else asdict(x) if is_dataclass(x) else vars(x)',
            '@app.get("/health")','def health(): return {"status":"ok"}'] if fast else
           ['"""Flask CRUD API; run python -m backend.api"""','from flask import Flask, jsonify, request, session',
             'import os',
            'from dataclasses import asdict, is_dataclass','from . import logic',
            'from .database import initialise',
            ('from .models import '+', '.join(e.name for e in spec.entities)) if spec.entities else 'from . import models', 'app=Flask(__name__)', 'initialise()',
            '# Security: restricted CORS + ephemeral session-token gate',
            '_ALLOWED_ORIGIN=os.environ.get("CORS_ORIGIN","null")',
            '_STUDIO_TOKEN=os.environ.get("STUDIO_TOKEN") or None',
            '@app.before_request', 'def _require_token():',
            '    if not request.path.startswith("/api/"): return',
            '    if request.method=="OPTIONS": return',
            '    if _STUDIO_TOKEN is None: return',
            '    if request.headers.get("X-Studio-Token","")!=_STUDIO_TOKEN: return jsonify(error="unauthorized"),401',
            '@app.after_request', 'def _cors(response):',
            '    if _ALLOWED_ORIGIN and _ALLOWED_ORIGIN!="null":',
            '        response.headers["Access-Control-Allow-Origin"]=_ALLOWED_ORIGIN',
            '    response.headers["Access-Control-Allow-Headers"]="Authorization, Content-Type, X-Studio-Token"',
            '    response.headers["Access-Control-Allow-Methods"]="GET, POST, PUT, DELETE, OPTIONS"',
            '    return response',
            '@app.route("/api/<path:path>",methods=["OPTIONS"])', 'def _preflight(path): return "",204',
            'def _data(x): return x if isinstance(x,dict) else asdict(x) if is_dataclass(x) else vars(x)',
            '@app.get("/health")','def health(): return jsonify(status="ok")'])
    if spec.authentication:
        if fast:
            out += ['from fastapi import Depends, Header', 'from starlette.middleware.sessions import SessionMiddleware',
                    'app.add_middleware(SessionMiddleware,secret_key=__import__("os").environ.get("AUTH_SECRET",""))',
                    'from . import auth',
                    'def require_user(authorization: str = Header(default="")):',
                    '    import jwt', '    token=authorization.removeprefix("Bearer ")',
                    '    try: user=auth.current_user(token)', '    except jwt.InvalidTokenError: user=None',
                    '    if not user: raise HTTPException(401,"Unauthorized")', '    return user']
        else:
            out += ['import os', 'app.secret_key=os.environ.get("AUTH_SECRET")',
                    'from . import auth', 'def _requires_auth(fn):', '    from functools import wraps',
                    '    @wraps(fn)', '    def wrapped(*args,**kwargs):', '        import jwt',
                    '        token=request.headers.get("Authorization","").removeprefix("Bearer ")',
                    '        try: user=auth.current_user(token)', '        except jwt.InvalidTokenError: user=None',
                    '        if not user: return jsonify(error="unauthorized"),401',
                    '        return fn(*args,**kwargs)', '    return wrapped']
    guard = '@_requires_auth' if spec.authentication and not fast else ''
    protect = ', dependencies=[Depends(require_user)]' if spec.authentication and fast else ''
    for e in spec.entities:
        t, route = _snake(e.name), _snake(e.name)+'s'
        if fast:
            out += [f'@app.get("/api/{route}"{protect})',f'def list_{t}(): return [_data(x) for x in logic.list_{t}()]',
                    f'@app.post("/api/{route}",status_code=201{protect})',f'def create_{t}(data:dict[str,Any]):',
                    f'    return logic.create_{t}(data)' if sqlalch else f'    return _data(logic.create_{t}({e.name}(**data)))',
                    f'@app.get("/api/{route}/{{item_id}}"{protect})',f'def get_{t}(item_id:int):',f'    x=logic.get_{t}(item_id)',
                    '    if x is None: raise HTTPException(404,"Not found")','    return _data(x)',
                    f'@app.put("/api/{route}/{{item_id}}"{protect})',f'def update_{t}(item_id:int,data:dict[str,Any]):',
                    f'    x=logic.update_{t}(item_id,data)' if sqlalch else f'    x=_update_{t}(item_id,data)',
                    '    if x is None: raise HTTPException(404,"Not found")','    return _data(x)',
                    f'@app.delete("/api/{route}/{{item_id}}",status_code=204{protect})',f'def delete_{t}(item_id:int):',
                    f'    if not logic.delete_{t}(item_id): raise HTTPException(404,"Not found")']
            if not sqlalch:
                out += [f'def _update_{t}(item_id,data):',f'    x=logic.get_{t}(item_id)',
                        '    if x is None: return None','    for k,v in data.items():',
                        f'        if k!={e.primary_key!r} and hasattr(x,k): setattr(x,k,v)',
                        f'    logic.update_{t}(x); return x']
        else:
            create=f'logic.create_{t}(request.get_json(silent=True) or {{}})' if sqlalch else f'logic.create_{t}({e.name}(**(request.get_json(silent=True) or {{}})))'
            update=f'logic.update_{t}(item_id, request.get_json(silent=True) or {{}})' if sqlalch else f'_update_{t}(item_id, request.get_json(silent=True) or {{}})'
            out += [f'@app.get("/api/{route}")',guard,f'def list_{t}(): return jsonify([_data(x) for x in logic.list_{t}()])',
                    f'@app.post("/api/{route}")',guard,f'def create_{t}(): return jsonify(_data({create})),201',
                    f'@app.get("/api/{route}/<int:item_id>")',guard,f'def get_{t}(item_id):',f'    x=logic.get_{t}(item_id)',
                    '    return (jsonify(_data(x)),200) if x is not None else (jsonify(error="not found"),404)',
                    f'@app.put("/api/{route}/<int:item_id>")',guard,f'def update_{t}(item_id):',
                    f'    x={update}',
                    '    return (jsonify(_data(x)),200) if x is not None else (jsonify(error="not found"),404)',
                    f'@app.delete("/api/{route}/<int:item_id>")',guard,f'def delete_{t}(item_id):',
                    f'    return ("",204) if logic.delete_{t}(item_id) else (jsonify(error="not found"),404)']
            if not sqlalch:
                out += [f'def _update_{t}(item_id,data):',f'    x=logic.get_{t}(item_id)',
                        '    if x is None: return None','    for k,v in data.items():',
                        f'        if k!={e.primary_key!r} and hasattr(x,k): setattr(x,k,v)',
                        f'    logic.update_{t}(x); return x']
    if spec.authentication:
        if fast:
            out += ['@app.post("/auth/register",status_code=201)', 'def register(data:dict[str,Any]):',
                    '    result,status=auth.register_user(data)', '    if status>=400: raise HTTPException(status,result["error"])', '    return result',
                    '@app.post("/auth/login")', 'def login(data:dict[str,Any]):', '    result,status=auth.login_user(data)',
                    '    if status>=400: raise HTTPException(status,result["error"])', '    return result',
                    '@app.post("/auth/logout",status_code=204)', 'def logout(authorization:str=Header()):',
                    '    return auth.logout_token(authorization.removeprefix("Bearer "))',
                    '@app.get("/auth/me")', 'def me(user=Depends(require_user)): return user',
                    'from authlib.integrations.starlette_client import OAuth', 'from starlette.requests import Request',
                    'oauth=OAuth();oauth.register(name="google",client_id=__import__("os").environ.get("GOOGLE_CLIENT_ID"),client_secret=__import__("os").environ.get("GOOGLE_CLIENT_SECRET"),server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",client_kwargs={"scope":"openid email profile"})',
                    '@app.get("/auth/oauth/google")', 'async def google_login(request:Request):',
                    '    return await oauth.google.authorize_redirect(request,str(request.url_for("google_callback")))',
                    '@app.get("/auth/oauth/google/callback",name="google_callback")', 'async def google_callback(request:Request):',
                    '    token=await oauth.google.authorize_access_token(request);profile=token.get("userinfo") or {}',
                    '    if not profile.get("email") or not profile.get("email_verified"): raise HTTPException(401,"Verified email required")',
                    '    from .auth import oauth_user', '    return oauth_user(profile["email"],profile.get("sub",""))']
        else:
            out += ['@app.post("/auth/register")', 'def register():', '    result,status=auth.register_user(request.get_json(silent=True) or {})', '    return jsonify(result),status',
                    '@app.post("/auth/login")', 'def login():', '    result,status=auth.login_user(request.get_json(silent=True) or {})', '    return jsonify(result),status',
                    '@app.post("/auth/logout")', 'def logout():', '    return auth.logout_token(request.headers.get("Authorization","").removeprefix("Bearer "))',
                    '@app.get("/auth/me")', 'def me():', '    import jwt', '    try: user=auth.current_user(request.headers.get("Authorization","").removeprefix("Bearer "))',
                    '    except jwt.InvalidTokenError: user=None', '    return (jsonify(user),200) if user else (jsonify(error="unauthorized"),401)',
                    'from authlib.integrations.flask_client import OAuth', 'oauth=OAuth(app)',
                    'oauth.register(name="google",client_id=os.environ.get("GOOGLE_CLIENT_ID"),client_secret=os.environ.get("GOOGLE_CLIENT_SECRET"),server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",client_kwargs={"scope":"openid email profile"})',
                    '@app.get("/auth/oauth/google")', 'def google_login():', '    import secrets',
                    '    from flask import session,url_for', '    nonce=secrets.token_urlsafe(24);session["oauth_nonce"]=nonce',
                    '    return oauth.google.authorize_redirect(url_for("google_callback",_external=True),nonce=nonce)',
                    '@app.get("/auth/oauth/google/callback")', 'def google_callback():',
                    '    from flask import session', '    nonce=session.pop("oauth_nonce",None)',
                    '    if not nonce: return jsonify(error="OAuth state missing"),400',
                    '    token=oauth.google.authorize_access_token(nonce=nonce);profile=token.get("userinfo") or {}',
                    '    if not profile.get("email") or not profile.get("email_verified"): return jsonify(error="Verified email required"),401',
                    '    return jsonify(auth.oauth_user(profile["email"],profile.get("sub","")))']
    if not fast:
        out += ['if __name__ == "__main__":', '    import argparse', '    parser=argparse.ArgumentParser()',
                '    parser.add_argument("--port",type=int,default=5000)', '    parser.add_argument("--host",default="0.0.0.0")',
                '    args=parser.parse_args()', '    app.run(host=args.host,port=args.port,debug=False)']
    return '\n'.join(out)+'\n'


def auth_source() -> str:
    return '''"""SQLite-backed password accounts and revocable JWT sessions. Set AUTH_SECRET to 32+ random characters."""
import os,sqlite3
from pathlib import Path
from datetime import datetime,timedelta,timezone
from werkzeug.security import check_password_hash,generate_password_hash
import jwt
_SECRET=os.environ.get("AUTH_SECRET","")
if len(_SECRET)<32: raise RuntimeError("Set AUTH_SECRET to at least 32 random characters")
_DB=Path(__file__).resolve().parent.parent/"data"/"auth.db"
def _db():
    _DB.parent.mkdir(parents=True,exist_ok=True); d=sqlite3.connect(_DB)
    d.execute("CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY,email TEXT UNIQUE NOT NULL,password_hash TEXT)")
    d.execute("CREATE TABLE IF NOT EXISTS revoked(token TEXT PRIMARY KEY)"); return d
def _token(uid):
    now=datetime.now(timezone.utc); return jwt.encode({"sub":str(uid),"iat":now,"exp":now+timedelta(minutes=30)},_SECRET,algorithm="HS256")
def register_user(data):
    email=str(data.get("email","")).strip().lower(); password=str(data.get("password",""))
    if "@" not in email or len(password)<12: return ({"error":"valid email and 12+ character password required"},400)
    d=_db()
    try:
        c=d.execute("INSERT INTO users(email,password_hash) VALUES(?,?)",(email,generate_password_hash(password,method="scrypt")));d.commit()
        return ({"access_token":_token(c.lastrowid),"token_type":"bearer"},201)
    except sqlite3.IntegrityError: return ({"error":"account already exists"},409)
    finally: d.close()
def login_user(data):
    d=_db()
    try: row=d.execute("SELECT id,password_hash FROM users WHERE email=?",(str(data.get("email","")).strip().lower(),)).fetchone()
    finally: d.close()
    if not row or not check_password_hash(row[1],str(data.get("password",""))): return ({"error":"invalid credentials"},401)
    return ({"access_token":_token(row[0]),"token_type":"bearer"},200)
def current_user(token):
    c=jwt.decode(token,_SECRET,algorithms=["HS256"]);d=_db()
    try:
        if d.execute("SELECT 1 FROM revoked WHERE token=?",(token,)).fetchone(): return None
        u=d.execute("SELECT id,email FROM users WHERE id=?",(c["sub"],)).fetchone();return {"id":u[0],"email":u[1]} if u else None
    finally:d.close()
def logout_token(token):
    jwt.decode(token,_SECRET,algorithms=["HS256"]);d=_db()
    try:d.execute("INSERT OR IGNORE INTO revoked(token) VALUES(?)",(token,));d.commit()
    finally:d.close()
    return "",204
def oauth_user(email,subject):
    d=_db()
    try:
        d.execute("INSERT INTO users(email,password_hash) VALUES(?,NULL) ON CONFLICT(email) DO NOTHING",(email.lower(),));d.commit()
        u=d.execute("SELECT id FROM users WHERE email=?",(email.lower(),)).fetchone()
        return {"access_token":_token(u[0]),"token_type":"bearer"}
    finally:d.close()
'''


def _graphql_api(spec: AppSpec) -> str:
    out = ['"""Strawberry GraphQL CRUD API; run uvicorn backend.api:app"""',
           'import strawberry', 'from strawberry.asgi import GraphQL', 'from fastapi import FastAPI',
           'from . import logic', 'from .database import initialise',
           ('from .models import '+', '.join(e.name for e in spec.entities)) if spec.entities else 'from . import models',
           '@strawberry.type', 'class Record:', '    id: int',
           '    data: strawberry.scalars.JSON']
    if spec.authentication:
        out += ['import jwt', 'from fastapi import Request, HTTPException', 'from . import auth',
                'async def get_context(request:Request): return {"request":request}',
                'def _require(info):',
                '    token=info.context["request"].headers.get("Authorization","").removeprefix("Bearer ")',
                '    try: user=auth.current_user(token)', '    except jwt.InvalidTokenError: user=None',
                '    if not user: raise Exception("Unauthorized")']
    out += ['@strawberry.type', 'class Query:', '    @strawberry.field',
            '    def health(self) -> str: return "ok"']
    for e in spec.entities:
        t = _snake(e.name)
        out += ['', '    @strawberry.field', f'    def list_{t}(self, info:strawberry.types.Info) -> list[Record]:']
        if spec.authentication: out.append('        _require(info)')
        out += [
                f'        rows=logic.list_{t}()',
                f'        return [Record(id=int(x.get({e.primary_key!r},0)) if isinstance(x,dict) else int(x.{e.primary_key}),data=x if isinstance(x,dict) else x.to_dict()) for x in rows]']
    sqlalch = spec.orm == 'sqlalchemy' or spec.database != 'sqlite'
    if not sqlalch:
        for e in spec.entities:
            t = _snake(e.name)
            out += ['', f'def _update_{t}(item_id,data):', f'    x=logic.get_{t}(item_id)',
                    '    if x is None: return None', '    for k,v in data.items():',
                    f'        if k!={e.primary_key!r} and hasattr(x,k): setattr(x,k,v)',
                    f'    logic.update_{t}(x); return x.to_dict()']
    out += ['', '@strawberry.type', 'class Mutation:']
    if not spec.entities: out.append('    pass')
    for e in spec.entities:
        t = _snake(e.name)
        create = f'logic.create_{t}(data)' if sqlalch else f'logic.create_{t}({e.name}(**data))'
        out += ['', '    @strawberry.mutation', f'    def create_{t}(self,data:strawberry.scalars.JSON,info:strawberry.types.Info) -> Record:']
        if spec.authentication: out.append('        _require(info)')
        out += [
                f'        x={create}',
                f'        return Record(id=int(x.get({e.primary_key!r},0)) if isinstance(x,dict) else int(x.{e.primary_key}),data=x if isinstance(x,dict) else x.to_dict())']
        update = f'logic.update_{t}(item_id,data)' if sqlalch else f'_update_{t}(item_id,data)'
        out += ['', '    @strawberry.mutation', f'    def update_{t}(self,item_id:int,data:strawberry.scalars.JSON,info:strawberry.types.Info) -> Record | None:']
        if spec.authentication: out.append('        _require(info)')
        out += [f'        x={update}', '        if x is None: return None',
                f'        return Record(id=int(x.get({e.primary_key!r},0)) if isinstance(x,dict) else int(x.{e.primary_key}),data=x if isinstance(x,dict) else x.to_dict())',
                '', '    @strawberry.mutation', f'    def delete_{t}(self,item_id:int,info:strawberry.types.Info) -> bool:']
        if spec.authentication: out.append('        _require(info)')
        out += [f'        return logic.delete_{t}(item_id)']
    out += ['', 'schema=strawberry.Schema(query=Query,mutation=Mutation)',
            'app=FastAPI(title=' + repr(spec.name) + ')', 'initialise()',
            'from fastapi.middleware.cors import CORSMiddleware',
            'app.add_middleware(CORSMiddleware,allow_origins=__import__("os").environ.get("CORS_ORIGINS","*").split(","),allow_methods=["*"],allow_headers=["*"])',
            'app.add_route("/graphql",GraphQL(schema,context_getter=get_context))' if spec.authentication else
            'app.add_route("/graphql",GraphQL(schema))']
    if spec.authentication:
        out += ['from typing import Any', 'from starlette.middleware.sessions import SessionMiddleware',
                'app.add_middleware(SessionMiddleware,secret_key=__import__("os").environ.get("AUTH_SECRET",""))',
                '@app.post("/auth/register",status_code=201)',
                'def register(data:dict[str,Any]):', '    result,status=auth.register_user(data)',
                '    if status>=400: raise HTTPException(status,result["error"])', '    return result',
                '@app.post("/auth/login")', 'def login(data:dict[str,Any]):',
                '    result,status=auth.login_user(data)', '    if status>=400: raise HTTPException(status,result["error"])', '    return result',
                'from fastapi import Header, Depends', '@app.post("/auth/logout",status_code=204)',
                'def logout(authorization:str=Header()): return auth.logout_token(authorization.removeprefix("Bearer "))',
                '@app.get("/auth/me")', 'def me(authorization:str=Header()):',
                '    token=authorization.removeprefix("Bearer ")',
                '    try: user=auth.current_user(token)', '    except jwt.InvalidTokenError: user=None',
                '    if not user: raise HTTPException(401,"Unauthorized")', '    return user',
                'from authlib.integrations.starlette_client import OAuth', 'from starlette.requests import Request',
                'oauth=OAuth();oauth.register(name="google",client_id=__import__("os").environ.get("GOOGLE_CLIENT_ID"),client_secret=__import__("os").environ.get("GOOGLE_CLIENT_SECRET"),server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",client_kwargs={"scope":"openid email profile"})',
                '@app.get("/auth/oauth/google")', 'async def google_login(request:Request):',
                '    return await oauth.google.authorize_redirect(request,str(request.url_for("google_callback")))',
                '@app.get("/auth/oauth/google/callback",name="google_callback")', 'async def google_callback(request:Request):',
                '    token=await oauth.google.authorize_access_token(request);profile=token.get("userinfo") or {}',
                '    if not profile.get("email") or not profile.get("email_verified"): raise HTTPException(401,"Verified email required")',
                '    return auth.oauth_user(profile["email"],profile.get("sub",""))']
    return '\n'.join(out) + '\n'


def alembic_ini() -> str:
    return '[alembic]\nscript_location = migrations\nprepend_sys_path = .\nsqlalchemy.url = sqlite:///data/app.db\n'


def migration_env() -> str:
    return '''import os
from alembic import context
from sqlalchemy import engine_from_config,pool
from backend.models import Base
config=context.config
config.set_main_option("sqlalchemy.url",os.environ.get("DATABASE_URL","sqlite:///data/app.db"))
target_metadata=Base.metadata
def run_migrations_online():
    engine=engine_from_config(config.get_section(config.config_ini_section),prefix="sqlalchemy.",poolclass=pool.NullPool)
    with engine.connect() as conn:
        context.configure(connection=conn,target_metadata=target_metadata,compare_type=True)
        with context.begin_transaction():context.run_migrations()
if context.is_offline_mode():
    context.configure(url=config.get_main_option("sqlalchemy.url"),target_metadata=target_metadata,literal_binds=True)
    with context.begin_transaction():context.run_migrations()
else:run_migrations_online()
'''


def migration_template() -> str:
    return '''"""${message}

Revision ID: ${up_revision}
Revises: ${down_revision | comma,n}
Create Date: ${create_date}
"""
from alembic import op
import sqlalchemy as sa
${imports if imports else ""}
revision = ${repr(up_revision)}
down_revision = ${repr(down_revision)}
branch_labels = ${repr(branch_labels)}
depends_on = ${repr(depends_on)}

def upgrade():
    ${upgrades if upgrades else "pass"}

def downgrade():
    ${downgrades if downgrades else "pass"}
'''
