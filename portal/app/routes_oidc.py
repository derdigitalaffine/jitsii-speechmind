"""Administrator-controlled OIDC settings and explicit account linking."""
import asyncio
import base64
import hashlib
import json
import secrets
import time
from urllib.parse import urlencode
from fastapi import Depends, HTTPException, Request
from fastapi.responses import Response
from sqlalchemy import select, delete, update
from sqlalchemy.orm import Session
from . import oidc, sessions
from .db import OidcFlow, OidcIdentity, OidcGroupGrant, GroupMember, User, Group, UserSession, PERMISSIONS, utcnow, set_setting
from .security import encrypt, decrypt
from .main import app, admin_user, current_user, get_db, check_csrf, render, redirect, flash, safe_next, session_user, rate_limit, start_session


def protect(response):
    response.headers.update({'Cache-Control':'no-store','Referrer-Policy':'no-referrer','X-Robots-Tag':'noindex, nofollow'})
    return response


def recent(request):
    return time.time()-float(request.session.get('auth_at',0))<900


def link_actor(request,db,flow):
    actor=session_user(request,db)
    if not actor or actor.id!=flow.initiator_id or sessions.current_hash(request)!=flow.initiator_sid or not recent(request) or (flow.link_uid!=actor.id and not actor.is_admin):raise HTTPException(403,'Bitte erneut anmelden und die Verknüpfung neu beginnen.')
    return actor


@app.get('/admin/oidc')
def oidc_settings(request:Request,user:User=Depends(admin_user),db:Session=Depends(get_db)):
    cfg=oidc.config(db)
    return protect(render(request,'admin_oidc.html',user,cfg=cfg,ready=oidc.usable(cfg),secret_set=bool(cfg['client_secret_enc']),
        groups=list(db.scalars(select(Group).order_by(Group.name))),permissions=PERMISSIONS,
        profile_keys=oidc.PROFILE_KEYS,profile_labels=profiles_labels(),callback=oidc.callback_url(),
        backchannel=oidc.settings.portal_base_url.rstrip('/')+'/auth/oidc/backchannel',logout_return=oidc.settings.portal_base_url.rstrip('/')+'/login'))


def profiles_labels():
    from . import profiles
    return {key:profiles.FIELDS[key][1] for key in oidc.PROFILE_KEYS}


@app.post('/admin/oidc',dependencies=[Depends(check_csrf)])
async def oidc_save(request:Request,user:User=Depends(admin_user),db:Session=Depends(get_db)):
    data=await request.form();cfg=oidc.config(db)
    if data.get('action')=='disable':
        cfg['enabled']=False;set_setting(db,'oidc_config',json.dumps(cfg));db.commit();flash(request,'OIDC-Anmeldung ausgeschaltet. Lokale Anmeldung bleibt erreichbar.');return redirect('/admin/oidc')
    cfg.update(provider='nextcloud' if data.get('provider')=='nextcloud' else 'oidc',label=str(data.get('label','Mit Nextcloud anmelden')).strip()[:100] or 'Mit Nextcloud anmelden')
    for key in ('base_url','discovery_url','issuer'):
        cfg[key]=oidc.url(str(data.get(key,'')).strip()) if str(data.get(key,'')).strip() else ''
    cfg['client_id']=str(data.get('client_id','')).strip()[:255]
    secret=str(data.get('client_secret',''))
    if secret:cfg['client_secret_enc']=encrypt(secret)
    cfg['auth_method']='client_secret_post' if data.get('auth_method')=='client_secret_post' else 'client_secret_basic'
    cfg['hours']=int(data.get('hours',8)) if str(data.get('hours',8)).isdigit() else 0
    if not 1<=cfg['hours']<=24:raise HTTPException(422,'Sitzungsdauer zwischen 1 und 24 Stunden wählen.')
    cfg['allowed_groups']=list(dict.fromkeys(g.strip() for g in str(data.get('allowed_groups','')).splitlines() if g.strip()))
    cfg['group_claim']=str(data.get('group_claim','groups')).strip()[:100] or 'groups'
    cfg['extra_origins']=[oidc.origin(v.strip()) for v in str(data.get('extra_origins','')).splitlines() if v.strip()]
    for key in ('auto_create','require_verified_email','sync_name','sync_email','backchannel','central_logout'):cfg[key]=data.get(key)=='1'
    group_ids=set(db.scalars(select(Group.id)));default=str(data.get('default_group','0'))
    cfg['default_group']=int(default) if default.isdigit() else 0
    if cfg['default_group'] and cfg['default_group'] not in group_ids:raise HTTPException(422,'Ungültige Standardgruppe.')
    cfg['default_permissions']=list(dict.fromkeys(k for k in data.getlist('permissions') if k in PERMISSIONS))
    mapping={}
    keys=data.getlist('map_key');values=data.getlist('map_group')
    if len(keys)!=len(values):raise HTTPException(422,'Ungültige Gruppenzuordnung.')
    for key,value in zip(keys,values):
        key=key.strip()
        if not key:continue
        if len(key)>255 or key in mapping or not str(value).isdigit() or int(value) not in group_ids:raise HTTPException(422,'Jede Anbietergruppe eindeutig einer vorhandenen Portalgruppe zuordnen.')
        mapping[key]=int(value)
    cfg['group_map']=mapping
    cfg['profile_map']={key:str(data.get('profile_'+key,'')).strip()[:100] for key in oidc.PROFILE_KEYS if str(data.get('profile_'+key,'')).strip()}
    active=data.get('enabled')=='1'
    if data.get('action')=='test':
        if not cfg['client_id'] or not cfg['client_secret_enc'] or not (cfg['base_url'] or cfg['discovery_url']):raise HTTPException(422,'Anbieteradresse, Client-ID und Client-Secret erforderlich.')
        doc=await asyncio.to_thread(oidc.discovery,cfg)
        keys=await asyncio.to_thread(oidc.fetch_json,oidc.endpoint(cfg,doc['jwks_uri']))
        if not isinstance(keys.get('keys'),list) or not any(isinstance(k,dict) and k.get('kty')=='RSA' for k in keys['keys']):raise HTTPException(422,'Anbieter liefert keinen RSA-Signaturschlüssel.')
        cfg['issuer']=doc['issuer'];cfg['metadata']={k:doc[k] for k in ('end_session_endpoint','backchannel_logout_supported') if k in doc}
        cfg['tested_hash']=oidc.fingerprint(cfg)
        flash(request,'Discovery und Signaturschlüssel geprüft. Client-Zugangsdaten werden beim tatsächlichen Login geprüft.')
    cfg['enabled']=active
    if active and cfg['tested_hash']!=oidc.fingerprint(cfg):raise HTTPException(422,'Bitte die geänderte Verbindung vor Aktivierung mit „Speichern & Verbindung prüfen“ testen.')
    set_setting(db,'oidc_config',json.dumps(cfg));db.commit();return redirect('/admin/oidc')


async def _oidc_start_redirect(request:Request,db:Session,cfg:dict,target:str,link_user=None,actor=None):
    doc=await asyncio.to_thread(oidc.discovery,cfg)
    flow,state,verifier,nonce=oidc.new_flow(request,db,cfg,target,link_user,actor)
    challenge=base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b'=').decode()
    query=dict(client_id=cfg['client_id'],redirect_uri=oidc.callback_url(),response_type='code',scope='openid profile email groups',state=state,nonce=nonce,code_challenge=challenge,code_challenge_method='S256')
    if link_user:query['prompt']='select_account'
    return protect(redirect(doc['authorization_endpoint']+('&' if '?' in doc['authorization_endpoint'] else '?')+urlencode(query)))


@app.get('/auth/oidc/start')
async def oidc_start_get(request:Request,db:Session=Depends(get_db)):
    """Normalen Login als Navigation starten; so kann eine Modul-Domain zuerst zur konfigurierten Portal-Domain wechseln."""
    cfg=oidc.config(db)
    if not oidc.usable(cfg):raise HTTPException(404,'OIDC-Anmeldung ist noch nicht eingerichtet.')
    rate_limit(request,'oidc-start',limit=20)
    target=safe_next(str(request.query_params.get('next','/')))
    return await _oidc_start_redirect(request,db,cfg,target)


@app.post('/auth/oidc/start',dependencies=[Depends(check_csrf)])
async def oidc_start(request:Request,db:Session=Depends(get_db)):
    cfg=oidc.config(db)
    if not oidc.usable(cfg):raise HTTPException(404,'OIDC-Anmeldung ist noch nicht eingerichtet.')
    rate_limit(request,'oidc-start',limit=20);data=await request.form();target=safe_next(str(data.get('next','/')))
    link_user=None;actor=None
    if data.get('link')=='1':
        actor=current_user(request,db)
        if not recent(request):flash(request,'Bitte für die Kontoverknüpfung erneut anmelden.','error');return redirect('/login?next=/profile/identity')
        value=str(data.get('user_id',actor.id))
        if not value.isdigit():raise HTTPException(422)
        link_user=db.get(User,int(value))
        if not link_user or not link_user.active or (link_user.id!=actor.id and not actor.is_admin):raise HTTPException(403)
    return await _oidc_start_redirect(request,db,cfg,target,link_user,actor)


def exchange(cfg,flow,code,doc):
    data=dict(grant_type='authorization_code',code=code,redirect_uri=oidc.callback_url(),code_verifier=decrypt(flow.verifier_enc))
    auth=None
    if cfg['auth_method']=='client_secret_basic':auth=httpx_auth(cfg)
    else:data.update(client_id=cfg['client_id'],client_secret=decrypt(cfg['client_secret_enc']))
    tokens=oidc.fetch_json(oidc.endpoint(cfg,doc['token_endpoint']),'POST',data,auth)
    claims=oidc.verify_token(cfg,doc,tokens.get('id_token'),flow.nonce_hash)
    for key,value in [('at_hash',tokens.get('access_token')),('c_hash',code)]:
        if claims.get(key):
            if not isinstance(value,str):raise HTTPException(400,'OIDC-Tokenbindung ungültig.')
            expected=base64.urlsafe_b64encode(hashlib.sha256(value.encode()).digest()[:16]).rstrip(b'=').decode()
            if not isinstance(claims[key],str) or not secrets.compare_digest(claims[key],expected):raise HTTPException(400,'OIDC-Tokenbindung ungültig.')
    if doc.get('userinfo_endpoint') and tokens.get('access_token'):
        if str(tokens.get('token_type','')).lower()!='bearer' or not isinstance(tokens['access_token'],str):raise HTTPException(400,'Ungültiger Zugriffstoken.')
        info=oidc.fetch_json(oidc.endpoint(cfg,doc['userinfo_endpoint']),headers={'Authorization':'Bearer '+tokens['access_token']})
        if info.get('sub')!=claims['sub']:raise HTTPException(400,'OIDC-Benutzerkennung stimmt nicht überein.')
        fields={'name','email','email_verified','given_name','family_name',cfg['group_claim'],*cfg['profile_map'].values()}
        for key in fields:
            if key in info and key not in {'iss','sub','aud','exp','iat','nonce','sid','azp'}:claims[key]=info[key]
    oidc.claims_policy(cfg,claims)
    return claims,tokens['id_token']


def httpx_auth(cfg):
    import httpx
    return httpx.BasicAuth(cfg['client_id'],decrypt(cfg['client_secret_enc']))


@app.get('/auth/oidc/callback')
async def oidc_callback(request:Request,db:Session=Depends(get_db)):
    cfg=oidc.config(db)
    if not oidc.usable(cfg):raise HTTPException(404)
    rate_limit(request,'oidc-callback',limit=30)
    try:
        flow=oidc.consume(request,db,cfg,request.query_params.get('state'))
        if request.query_params.get('error'):raise HTTPException(400,'Die Anmeldung beim Anbieter wurde abgebrochen.')
        code=request.query_params.get('code','')
        if not code or len(code)>4096:raise HTTPException(400,'Anmeldecode fehlt.')
        if flow.link_uid:link_actor(request,db,flow)
        doc=await asyncio.to_thread(oidc.discovery,cfg)
        claims,id_token=await asyncio.to_thread(exchange,cfg,flow,code,doc)
        if flow.link_uid:
            flow.payload_enc=encrypt(json.dumps({'claims':claims}));db.commit();request.session['oidc_link_flow']=flow.id
            return protect(redirect('/profile/identity/confirm'))
        identity,user=oidc.identify(db,cfg,claims)
        flow.user_id=user.id;flow.payload_enc=encrypt(json.dumps({'identity':identity.id,'sid':claims.get('sid',''),'id_token':id_token}));db.commit()
        return protect(start_session(request,db,user,flow.target,oidc_flow=flow))
    except HTTPException as error:
        db.rollback();flash(request,str(error.detail),'error');return protect(redirect('/login'))


@app.get('/profile/identity')
def oidc_profile(request:Request,user:User=Depends(current_user),db:Session=Depends(get_db)):
    target=user
    uid=request.query_params.get('user_id')
    if uid:
        if not user.is_admin or not uid.isdigit():raise HTTPException(403)
        target=db.get(User,int(uid))
        if not target:raise HTTPException(404)
    identities=list(db.scalars(select(OidcIdentity).where(OidcIdentity.user_id==target.id)))
    return protect(render(request,'profile_identity.html',user,target=target,identities=identities,ready=oidc.usable(oidc.config(db)),recent=recent(request)))


@app.get('/profile/identity/confirm')
def oidc_link_confirm(request:Request,user:User=Depends(current_user),db:Session=Depends(get_db)):
    flow=db.get(OidcFlow,request.session.get('oidc_link_flow',0))
    if not flow or flow.completed or flow.expires_at<=utcnow() or flow.config_hash!=oidc.fingerprint(oidc.config(db)):raise HTTPException(400)
    link_actor(request,db,flow)
    claims=json.loads(decrypt(flow.payload_enc))['claims']
    return protect(render(request,'oidc_confirm.html',user,target=db.get(User,flow.link_uid),claims=claims,issuer=oidc.config(db)['issuer']))


@app.post('/profile/identity/confirm',dependencies=[Depends(check_csrf)])
def oidc_link_apply(request:Request,user:User=Depends(current_user),db:Session=Depends(get_db)):
    flow=db.get(OidcFlow,request.session.get('oidc_link_flow',0));cfg=oidc.config(db)
    if not flow or flow.completed or flow.expires_at<=utcnow() or flow.config_hash!=oidc.fingerprint(cfg) or not oidc.usable(cfg):raise HTTPException(400)
    link_actor(request,db,flow)
    changed=db.execute(update(OidcFlow).where(OidcFlow.id==flow.id,OidcFlow.completed.is_(False)).values(completed=True))
    if changed.rowcount!=1:raise HTTPException(409)
    claims=json.loads(decrypt(flow.payload_enc))['claims'];target=db.get(User,flow.link_uid)
    oidc.identify(db,cfg,claims,target);flow.payload_enc='';flow.verifier_enc='';db.commit();request.session.pop('oidc_link_flow',None)
    flash(request,'OIDC-Konto ausdrücklich verknüpft.');return redirect('/profile/identity'+(f'?user_id={target.id}' if target.id!=user.id else ''))


@app.post('/profile/identity/{iid:int}/unlink',dependencies=[Depends(check_csrf)])
def oidc_unlink(request:Request,iid:int,user:User=Depends(current_user),db:Session=Depends(get_db)):
    identity=db.get(OidcIdentity,iid)
    if not identity or (identity.user_id!=user.id and not user.is_admin) or not recent(request):raise HTTPException(403,'Bitte erneut anmelden.')
    target=db.get(User,identity.user_id)
    if not target.password_set:raise HTTPException(409,'Vor dem Entfernen zuerst einen lokalen Zugang einrichten, damit das Konto erreichbar bleibt.')
    for grant in db.scalars(select(OidcGroupGrant).where(OidcGroupGrant.identity_id==iid)):
        oidc.remove_group_grant(db,identity,grant)
    db.delete(identity);db.commit();flash(request,'Verknüpfung entfernt; OIDC-Sitzungen beendet.');return redirect('/profile/identity')


@app.post('/auth/oidc/backchannel')
async def oidc_backchannel(request:Request,db:Session=Depends(get_db)):
    cfg=oidc.config(db)
    if not oidc.usable(cfg) or not cfg['backchannel']:raise HTTPException(404)
    rate_limit(request,'oidc-backchannel',limit=120);data=await request.form();token=str(data.get('logout_token',''))
    if len(token)>32768:raise HTTPException(400)
    doc=await asyncio.to_thread(oidc.discovery,cfg)
    claims=await asyncio.to_thread(oidc.verify_token,cfg,doc,token,None,True)
    oidc.apply_logout(db,cfg,claims)
    return protect(Response(status_code=200))


@app.post('/auth/oidc/logout',dependencies=[Depends(check_csrf)])
async def oidc_logout(request:Request,user:User=Depends(current_user),db:Session=Depends(get_db)):
    cfg=oidc.config(db);row=db.scalar(select(UserSession).where(UserSession.sid_hash==sessions.current_hash(request)))
    target='/login'
    if row and row.oidc_identity_id and cfg['central_logout'] and oidc.usable(cfg):
        try:doc=await asyncio.to_thread(oidc.discovery,cfg)
        except HTTPException:doc={}
        if doc.get('end_session_endpoint'):
            target=doc['end_session_endpoint']+('&' if '?' in doc['end_session_endpoint'] else '?')+urlencode({'id_token_hint':decrypt(row.oidc_token_enc),'post_logout_redirect_uri':oidc.settings.portal_base_url.rstrip('/')+'/login','client_id':cfg['client_id']})
    sessions.end(request,db);request.session.clear();return protect(redirect(target))
