"""OIDC code + S256 login; identities use issuer/subject, never an email join."""
import base64
import hashlib
import hmac
import json
import re
import secrets
import time
from datetime import timedelta
from urllib.parse import urlencode, urlsplit
import httpx
import jwt
from fastapi import HTTPException
from sqlalchemy import select, update, delete
from .db import (OidcIdentity, OidcFlow, OidcGroupGrant, OidcLogoutToken, GroupMember, Group,
                 User, UserSession, get_settings, set_setting, utcnow)
from . import profiles, sessions
from .security import encrypt, decrypt, hash_password
from .config import settings

PROFILE_KEYS = ['given_name','family_name','organization','department','job_title','work_phone','locale','zoneinfo']
DEFAULT = dict(enabled=False,label='Mit Nextcloud anmelden',provider='nextcloud',base_url='',discovery_url='',
    issuer='',client_id='',client_secret_enc='',auth_method='client_secret_basic',allowed_groups=[],group_claim='groups',
    group_map={},default_group=0,default_permissions=[],auto_create=True,require_verified_email=True,
    sync_name=True,sync_email=True,profile_map={},hours=8,backchannel=True,central_logout=True,extra_origins=[],tested_hash='')


def digest(value):return hashlib.sha256(value.encode()).hexdigest()


def config(db):
    try:value=json.loads(get_settings(db).get('oidc_config','{}'))
    except ValueError:value={}
    return {**DEFAULT,**value} if isinstance(value,dict) else dict(DEFAULT)


def fingerprint(cfg):return digest(json.dumps({k:v for k,v in cfg.items() if k not in {'enabled','tested_hash','metadata'}},sort_keys=True))


def usable(cfg):return bool(cfg['enabled'] and cfg['issuer'] and cfg['client_id'] and cfg['tested_hash']==fingerprint(cfg))


def url(value):
    try:
        parsed=urlsplit(value);parsed.port
    except (ValueError,TypeError):raise HTTPException(422,'Ungültige OIDC-Adresse.')
    if parsed.scheme!='https' or not parsed.hostname or parsed.username or parsed.password or parsed.fragment or any(ord(c)<33 for c in value):raise HTTPException(422,'OIDC-Adressen müssen vollständige HTTPS-Adressen ohne Zugangsdaten sein.')
    return value


def origin(value):
    p=urlsplit(url(value));return p.scheme+'://'+p.netloc.lower()


def endpoint(cfg,value):
    allowed={origin(v) for v in [cfg['base_url'],cfg['discovery_url'],cfg['issuer'],*cfg['extra_origins']] if v}
    if origin(value) not in allowed:raise HTTPException(422,'OIDC-Endpunkt verwendet einen nicht freigegebenen Server.')
    return url(value)


def fetch_json(address,method='GET',data=None,auth=None,headers=None):
    try:
        with httpx.Client(timeout=8,follow_redirects=False,trust_env=False) as client:
            with client.stream(method,address,data=data,auth=auth,headers=headers) as response:
                response.raise_for_status();body=bytearray()
                for chunk in response.iter_bytes():
                    body.extend(chunk)
                    if len(body)>1024*1024:raise ValueError()
                value=json.loads(body)
                if not isinstance(value,dict):raise ValueError()
                return value
    except (httpx.HTTPError,ValueError):raise HTTPException(503,'OIDC-Anbieter nicht erreichbar oder Antwort ungültig. Bitte Einstellungen und Verbindung prüfen.')


def discovery(cfg):
    address=cfg['discovery_url'] or url(cfg['base_url']).rstrip('/')+'/index.php/apps/oidc/openid-configuration'
    doc=fetch_json(endpoint(cfg,address))
    issuer=url(str(doc.get('issuer','')))
    if cfg['issuer'] and issuer!=cfg['issuer']:raise HTTPException(422,'Die Anbieterkennung (Issuer) stimmt nicht mit der Konfiguration überein.')
    endpoint(cfg,issuer)
    for key in ('authorization_endpoint','token_endpoint','jwks_uri'):
        endpoint(cfg,str(doc.get(key,'')))
    for key in ('userinfo_endpoint','end_session_endpoint'):
        if doc.get(key):endpoint(cfg,doc[key])
    if 'RS256' not in doc.get('id_token_signing_alg_values_supported',['RS256']):raise HTTPException(422,'Bitte RS256-Signaturen am OIDC-Anbieter konfigurieren.')
    if 'code' not in doc.get('response_types_supported',['code']):raise HTTPException(422,'Authorization-Code-Anmeldung wird nicht angeboten.')
    if 'code_challenge_methods_supported' in doc and 'S256' not in doc['code_challenge_methods_supported']:raise HTTPException(422,'PKCE S256 muss unterstützt werden.')
    if cfg['auth_method'] not in doc.get('token_endpoint_auth_methods_supported',['client_secret_basic']):raise HTTPException(422,'Die gewählte Client-Authentifizierung wird nicht angeboten.')
    return doc


def callback_url():return settings.portal_base_url.rstrip('/')+'/auth/oidc/callback'


def verify_token(cfg,doc,token,nonce=None,logout=False):
    try:
        if not isinstance(token,str) or len(token)>32768:raise ValueError()
        header=jwt.get_unverified_header(token)
        if header.get('alg')!='RS256':raise ValueError()
        keys=fetch_json(endpoint(cfg,doc['jwks_uri'])).get('keys',[])
        if not isinstance(keys,list) or len(keys)>100:raise ValueError()
        candidates=[k for k in keys if isinstance(k,dict) and k.get('kty')=='RSA' and k.get('use','sig')=='sig' and k.get('alg','RS256')=='RS256' and (not header.get('kid') or k.get('kid')==header['kid'])]
        if len(candidates)!=1:raise ValueError()
        key=jwt.PyJWK.from_dict(candidates[0],algorithm='RS256').key
        if key.key_size<2048:raise ValueError()
        required=['iss','aud','iat','sub','exp'] if not logout else ['iss','aud','iat','jti','events']
        claims=jwt.decode(token,key,algorithms=['RS256'],audience=cfg['client_id'],issuer=cfg['issuer'],leeway=30,options={'require':required})
        if not isinstance(claims.get('iat'),(int,float)) or claims['iat']>time.time()+30:raise ValueError()
        aud=claims['aud']
        if (isinstance(aud,list) and len(aud)>1 and claims.get('azp')!=cfg['client_id']) or (claims.get('azp') and claims['azp']!=cfg['client_id']):raise ValueError()
        if claims.get('sid') is not None and (not isinstance(claims['sid'],str) or not claims['sid'] or len(claims['sid'])>255):raise ValueError()
        if logout:
            if not isinstance(claims.get('jti'),str) or not claims['jti'] or len(claims['jti'])>255:raise ValueError()
            if claims.get('sub') is not None and (not isinstance(claims['sub'],str) or not claims['sub'] or len(claims['sub'])>255):raise ValueError()
            events=claims.get('events')
            if not isinstance(events,dict) or not isinstance(events.get('http://schemas.openid.net/event/backchannel-logout'),dict) or 'nonce' in claims or not (claims.get('sub') or claims.get('sid')) or abs(time.time()-claims['iat'])>300:raise ValueError()
        elif not isinstance(claims.get('sub'),str) or not claims['sub'] or len(claims['sub'])>255 or not isinstance(claims.get('nonce'),str) or not nonce or not hmac.compare_digest(digest(claims['nonce']),nonce):raise ValueError()
        return claims
    except (jwt.PyJWTError,ValueError,KeyError,TypeError):raise HTTPException(400,'Die OIDC-Antwort konnte nicht sicher bestätigt werden. Bitte neu anmelden.')


def claims_policy(cfg,claims):
    groups=claims.get(cfg['group_claim'],[])
    if not isinstance(groups,list) or any(not isinstance(g,str) for g in groups):raise HTTPException(403,'Ungültige Gruppenzuordnung vom Anbieter.')
    if cfg['allowed_groups'] and not set(groups)&set(cfg['allowed_groups']):raise HTTPException(403,'Ihr Nextcloud-Konto ist für dieses Portal nicht zugelassen.')
    email=claims.get('email')
    if not isinstance(email,str) or len(email)>255 or not re.fullmatch(r'[^\s@<>]+@[^\s@<>]+\.[^\s@<>]+',email):raise HTTPException(403,'Der Anbieter muss eine gültige E-Mail-Adresse liefern.')
    if cfg['require_verified_email'] and claims.get('email_verified') is not True:raise HTTPException(403,'Der Anbieter muss die E-Mail-Adresse als bestätigt ausweisen.')
    return groups,email.strip().lower()


def remove_group_grant(db,identity,grant):
    """Remove only membership owned solely by this provider identity."""
    member=db.get(GroupMember,(grant.group_id,identity.user_id))
    other=db.scalar(select(OidcGroupGrant.identity_id).join(OidcIdentity,OidcIdentity.id==OidcGroupGrant.identity_id).where(
        OidcIdentity.user_id==identity.user_id,OidcGroupGrant.group_id==grant.group_id,OidcGroupGrant.identity_id!=identity.id).limit(1))
    db.delete(grant)
    if member and not member.manual and other is None:db.delete(member)


def sync(db,cfg,identity,claims):
    groups,email=claims_policy(cfg,claims);user=db.get(User,identity.user_id)
    if not user or not user.active:raise HTTPException(403,'Dieses Portalkonto ist gesperrt.')
    collision=db.scalar(select(User.id).where(User.email==email,User.id!=user.id))
    if cfg['sync_email'] and collision:raise HTTPException(409,'Die neue E-Mail-Adresse ist bereits einem anderen Portalkonto zugeordnet. Bitte die Administration kontaktieren.')
    if cfg['sync_email']:user.email=email
    if cfg['sync_name']:
        name=claims.get('name') or ' '.join(str(claims.get(k,'')).strip() for k in ('given_name','family_name')).strip()
        if isinstance(name,str) and name.strip():user.name=name.strip()[:255]
    profile=profiles.read(user)
    for key,claim in cfg['profile_map'].items():
        value=claims.get(claim)
        if key in PROFILE_KEYS and isinstance(value,str):profile[key]=value
    try:user.profile_data_enc=profiles.store(profile)
    except ValueError:raise HTTPException(422,'Ein übermitteltes Profilfeld ist ungültig. Bitte die Profilzuordnung prüfen.')
    wanted={int(cfg['group_map'][g]) for g in groups if g in cfg['group_map']}
    grants=list(db.scalars(select(OidcGroupGrant).where(OidcGroupGrant.identity_id==identity.id)))
    for grant in grants:
        if grant.group_id not in wanted:
            remove_group_grant(db,identity,grant)
    for gid in wanted:
        if not db.get(Group,gid):continue
        if not db.get(OidcGroupGrant,(identity.id,gid)):db.add(OidcGroupGrant(identity_id=identity.id,group_id=gid))
        if not db.get(GroupMember,(gid,user.id)):db.add(GroupMember(group_id=gid,user_id=user.id,manual=False))
    identity.claims_enc=encrypt(json.dumps(claims));identity.last_login_at=utcnow();db.flush();db.expire(user,['groups'])
    return user


def identify(db,cfg,claims,target=None):
    claims_policy(cfg,claims)
    identity=db.scalar(select(OidcIdentity).where(OidcIdentity.issuer==cfg['issuer'],OidcIdentity.subject==claims['sub']))
    if identity:
        if target and identity.user_id!=target.id:raise HTTPException(409,'Dieses OIDC-Konto ist bereits mit einem anderen Portalkonto verknüpft.')
        return identity,sync(db,cfg,identity,claims)
    if target:
        if db.scalar(select(OidcIdentity.id).where(OidcIdentity.issuer==cfg['issuer'],OidcIdentity.user_id==target.id)):raise HTTPException(409,'Dieses Portalkonto hat bereits eine Verknüpfung mit dem Anbieter.')
        user=target
    else:
        email=claims['email'].strip().lower()
        if db.scalar(select(User.id).where(User.email==email)):raise HTTPException(409,'Bitte zuerst mit Ihrem bestehenden Portalkonto anmelden und unter Sicherheit die Nextcloud-Verknüpfung bestätigen.')
        if not cfg['auto_create']:raise HTTPException(403,'Bitte zuerst ein Portalkonto durch die Administration anlegen lassen.')
        user=User(email=email,name=str(claims.get('name') or email)[:255],password_hash=hash_password(secrets.token_urlsafe(64)),password_set=False,must_change_password=False,permissions=','.join(cfg['default_permissions']),is_admin=False)
        db.add(user);db.flush()
        if cfg['default_group'] and db.get(Group,cfg['default_group']):db.add(GroupMember(user_id=user.id,group_id=cfg['default_group'],manual=True))
    identity=OidcIdentity(user_id=user.id,issuer=cfg['issuer'],subject=claims['sub']);db.add(identity);db.flush()
    return identity,sync(db,cfg,identity,claims)


def new_flow(request,db,cfg,target,link_user=None,initiator=None):
    browser=request.session.get('oidc_browser') or secrets.token_urlsafe(32);request.session['oidc_browser']=browser
    state=secrets.token_urlsafe(32);verifier=secrets.token_urlsafe(48);nonce=secrets.token_urlsafe(32)
    flow=OidcFlow(state_hash=digest(state),browser_hash=digest(browser),config_hash=fingerprint(cfg),verifier_enc=encrypt(verifier),nonce_hash=digest(nonce),target=target[:1000],
        link_uid=link_user.id if link_user else None,initiator_id=initiator.id if initiator else None,initiator_sid=sessions.current_hash(request) or '',expires_at=utcnow()+timedelta(minutes=10))
    db.add(flow);db.commit();return flow,state,verifier,nonce


def consume(request,db,cfg,state):
    browser=request.session.get('oidc_browser','')
    if not isinstance(state,str) or len(state)>100 or not browser:raise HTTPException(400,'Anmeldung abgelaufen. Bitte neu beginnen.')
    flow=db.scalar(select(OidcFlow).where(OidcFlow.state_hash==digest(state)))
    if not flow or flow.used or flow.expires_at<=utcnow() or flow.config_hash!=fingerprint(cfg) or not hmac.compare_digest(flow.browser_hash,digest(browser)):raise HTTPException(400,'Anmeldung abgelaufen oder bereits verwendet. Bitte neu beginnen.')
    changed=db.execute(update(OidcFlow).where(OidcFlow.id==flow.id,OidcFlow.used.is_(False)).values(used=True))
    if changed.rowcount!=1:raise HTTPException(400)
    db.commit();return flow


def bind_session(db,row,flow,user):
    cfg=config(db)
    if not flow or not flow.used or flow.completed or flow.user_id!=user.id or flow.expires_at<=utcnow() or flow.config_hash!=fingerprint(cfg) or not usable(cfg):raise HTTPException(403,'OIDC-Anmeldung abgelaufen. Bitte neu beginnen.')
    payload=json.loads(decrypt(flow.payload_enc));identity=db.get(OidcIdentity,payload['identity'])
    if not identity or identity.user_id!=user.id:raise HTTPException(403)
    claims_policy(cfg,json.loads(decrypt(identity.claims_enc)))
    changed=db.execute(update(OidcFlow).where(OidcFlow.id==flow.id,OidcFlow.completed.is_(False)).values(completed=True))
    if changed.rowcount!=1:raise HTTPException(403)
    row.oidc_identity_id=identity.id;row.oidc_sid=payload.get('sid','');row.oidc_token_enc=encrypt(payload['id_token']);row.expires_at=utcnow()+timedelta(hours=cfg['hours'])
    row.method='oidc+2fa' if row.method=='2fa' else 'oidc'
    flow.verifier_enc='';flow.payload_enc=''


def session_valid(db,row,cfg=None):
    if not row.oidc_identity_id:return True
    cfg=cfg or config(db);identity=db.get(OidcIdentity,row.oidc_identity_id)
    if not usable(cfg) or not identity or identity.issuer!=cfg['issuer'] or not row.expires_at or row.expires_at<=utcnow():return False
    try:claims_policy(cfg,json.loads(decrypt(identity.claims_enc)))
    except (HTTPException,ValueError):return False
    return True


def backchannel(db,cfg,doc,token):
    if not cfg['backchannel']:raise HTTPException(404)
    claims=verify_token(cfg,doc,token,logout=True)
    apply_logout(db,cfg,claims)


def apply_logout(db,cfg,claims):
    replay=digest(cfg['issuer']+'\0'+str(claims['jti']))
    if db.get(OidcLogoutToken,replay):return
    ids=select(OidcIdentity.id).where(OidcIdentity.issuer==cfg['issuer'])
    if claims.get('sub'):ids=ids.where(OidcIdentity.subject==claims['sub'])
    query=delete(UserSession).where(UserSession.oidc_identity_id.in_(ids))
    if claims.get('sid'):query=query.where(UserSession.oidc_sid==claims['sid'])
    db.execute(query);db.add(OidcLogoutToken(digest=replay));db.commit()


def purge(db):
    db.execute(delete(OidcFlow).where(OidcFlow.expires_at<utcnow()))
    db.execute(delete(OidcLogoutToken).where(OidcLogoutToken.created_at<utcnow()-timedelta(days=1)))
