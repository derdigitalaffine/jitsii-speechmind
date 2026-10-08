import json
import secrets
import time
from datetime import timedelta
from urllib.parse import urlsplit, parse_qs
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import HTTPException
from sqlalchemy import select, delete
from app import oidc, main, sessions, twofa
from app.db import (User, Group, GroupMember, OidcIdentity, OidcFlow, OidcGroupGrant, UserSession,
                    OidcLogoutToken, get_settings, set_setting, utcnow)
from app.security import encrypt, hash_password
from conftest import client, login, csrf_of


@pytest.fixture
def provider(db,monkeypatch):
    old=get_settings(db);suffix=secrets.token_hex(5)
    key=rsa.generate_private_key(public_exponent=65537,key_size=2048)
    public=json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(key.public_key()));public.update(kid='test-key',use='sig',alg='RS256')
    cfg={**oidc.DEFAULT,'base_url':'https://cloud.example.org','issuer':'https://cloud.example.org/index.php/apps/oidc',
        'client_id':'portal-client','client_secret_enc':encrypt('test-client-secret'), 'allowed_groups':['employees'],'enabled':True}
    cfg['tested_hash']=oidc.fingerprint(cfg);set_setting(db,'oidc_config',json.dumps(cfg));db.commit()
    doc={'issuer':cfg['issuer'],'authorization_endpoint':cfg['issuer']+'/authorize','token_endpoint':cfg['issuer']+'/token',
         'jwks_uri':cfg['issuer']+'/jwks','userinfo_endpoint':cfg['issuer']+'/userinfo','end_session_endpoint':cfg['issuer']+'/logout',
         'id_token_signing_alg_values_supported':['RS256'],'response_types_supported':['code'],'code_challenge_methods_supported':['S256'],
         'token_endpoint_auth_methods_supported':['client_secret_basic'],'backchannel_logout_supported':True}
    claims={'iss':cfg['issuer'],'aud':cfg['client_id'],'iat':int(time.time()),'exp':int(time.time())+600,'sub':'subject-'+suffix,
            'email':'oidc-'+suffix+'@example.org','email_verified':True,'name':'OIDC Person','groups':['employees'],'sid':'session-'+suffix}
    state={'cfg':cfg,'doc':doc,'claims':claims,'key':key,'public':public,'suffix':suffix,'token_data':None,'info':None}
    def fetch(address,method='GET',data=None,auth=None,headers=None):
        if address.endswith('openid-configuration'):return doc
        if address==doc['jwks_uri']:return {'keys':[public]}
        if address==doc['token_endpoint']:
            assert method=='POST' and data['code_verifier'] and data['redirect_uri']==oidc.callback_url()
            state['token_data']=data
            return {'id_token':jwt.encode(state['claims'],key,algorithm='RS256',headers={'kid':'test-key'}),'access_token':'access-test','token_type':'Bearer'}
        if address==doc['userinfo_endpoint']:return state['info'] if state['info'] is not None else {k:v for k,v in state['claims'].items() if k in {'sub','email','email_verified','name','groups'}}
        raise AssertionError(address)
    monkeypatch.setattr(oidc,'fetch_json',fetch)
    yield state
    db.rollback()
    db.execute(delete(OidcFlow));db.execute(delete(OidcLogoutToken))
    for identity in db.scalars(select(OidcIdentity).where(OidcIdentity.issuer==cfg['issuer'])):db.delete(identity)
    db.flush()
    for user in db.scalars(select(User).where(User.email.like('%'+suffix+'%'))):db.delete(user)
    for group in db.scalars(select(Group).where(Group.name.like('%'+suffix+'%'))):db.delete(group)
    set_setting(db,'oidc_config',old.get('oidc_config','{}'))
    for k in ('mfa_required','mfa_totp_allowed','mfa_email_allowed'):set_setting(db,k,old.get(k,''))
    db.commit()


def begin(c,provider,link=None):
    page=c.get('/login');data={'csrf':csrf_of(page.text),'next':'/seminare'}
    if link:data.update(link='1',user_id=str(link))
    r=c.post('/auth/oidc/start',data=data);assert r.status_code==303
    params=parse_qs(urlsplit(r.headers['location']).query)
    assert params['code_challenge_method']==['S256'] and 'nonce' in params
    provider['claims']['nonce']=params['nonce'][0]
    return params['state'][0]


def callback(c,state):return c.get('/auth/oidc/callback',params={'state':state,'code':'test-code'})


def test_code_flow_pkce_minimal_account_and_hard_session_expiry(db,provider):
    c=client();state=begin(c,provider);r=callback(c,state)
    assert r.status_code==303 and r.headers['location']=='/seminare'
    user=db.scalar(select(User).where(User.email==provider['claims']['email']))
    assert user and not user.is_admin and user.permissions=='' and not user.password_set
    row=db.scalar(select(UserSession).where(UserSession.user_id==user.id));assert row.method=='oidc' and row.oidc_identity_id
    assert row.expires_at<=utcnow()+timedelta(hours=8,seconds=2)
    assert 'test-client-secret' not in c.cookies.get('jsm_session') and provider['token_data']['code_verifier'] not in c.cookies.get('jsm_session')
    assert c.get('/profile/identity').status_code==200
    row.expires_at=utcnow()-timedelta(seconds=1);db.commit();assert c.get('/profile/identity').status_code==303


def test_state_browser_binding_replay_and_nonce_failure(db,provider):
    c=client();state=begin(c,provider);other=client();assert callback(other,state).headers['location']=='/login'
    provider['claims']['nonce']='wrong';assert callback(c,state).headers['location']=='/login'
    assert not db.scalar(select(OidcIdentity.id))
    assert callback(c,state).headers['location']=='/login'
    flow=db.scalar(select(OidcFlow).where(OidcFlow.state_hash==oidc.digest(state)));assert flow.used


def test_no_email_auto_merge_and_explicit_link_confirmation(db,provider):
    user=User(email=provider['claims']['email'],name='Local Person',password_hash=hash_password('passwort-test-123'),permissions='video');db.add(user);db.commit()
    c=client();state=begin(c,provider);assert callback(c,state).headers['location']=='/login'
    assert not db.scalar(select(OidcIdentity.id))
    c=login(user.email,'passwort-test-123');state=begin(c,provider,user.id);assert callback(c,state).headers['location']=='/profile/identity/confirm'
    assert not db.scalar(select(OidcIdentity.id))
    page=c.get('/profile/identity/confirm');assert page.status_code==200
    assert c.post('/profile/identity/confirm',data={'csrf':csrf_of(page.text)}).status_code==303
    identity=db.scalar(select(OidcIdentity));assert identity.user_id==user.id
    db.refresh(user);assert user.permissions=='video'
    c2=client();state=begin(c2,provider);assert callback(c2,state).headers['location']=='/seminare'
    assert db.scalars(select(User).where(User.email==user.email)).all()==[user]


def test_group_sync_removes_only_oidc_memberships(db,provider):
    g=Group(name='mapped-'+provider['suffix']);manual=Group(name='manual-'+provider['suffix']);db.add_all([g,manual]);db.commit()
    cfg=provider['cfg'];cfg['group_map']={'employees':g.id};cfg['tested_hash']=oidc.fingerprint(cfg);set_setting(db,'oidc_config',json.dumps(cfg));db.commit()
    identity,user=oidc.identify(db,cfg,provider['claims']);db.add(GroupMember(group_id=manual.id,user_id=user.id,manual=True));db.commit()
    assert not db.get(GroupMember,(g.id,user.id)).manual
    claims={**provider['claims'],'groups':['other']};cfg['allowed_groups']=[]
    oidc.sync(db,cfg,identity,claims);db.commit()
    assert not db.get(GroupMember,(g.id,user.id)) and db.get(GroupMember,(manual.id,user.id))
    oidc.sync(db,cfg,identity,provider['claims']);db.commit();db.get(GroupMember,(g.id,user.id)).manual=True;db.commit()
    oidc.sync(db,cfg,identity,claims);db.commit();assert db.get(GroupMember,(g.id,user.id))


def test_mfa_is_not_bypassed(db,provider):
    cfg=provider['cfg'];identity,user=oidc.identify(db,cfg,provider['claims']);secret=twofa.new_secret();twofa.enable_totp(user,secret)
    set_setting(db,'mfa_totp_allowed','1');set_setting(db,'mfa_required','off');db.commit()
    c=client();state=begin(c,provider);r=callback(c,state);assert r.headers['location']=='/login/2fa'
    assert not db.scalar(select(UserSession).where(UserSession.user_id==user.id))
    page=c.get('/login/2fa');r=c.post('/login/2fa',data={'csrf':csrf_of(page.text),'method':'totp','code':twofa.totp_now(secret)})
    assert r.status_code==303 and r.headers['location']=='/seminare'
    row=db.scalar(select(UserSession).where(UserSession.user_id==user.id));assert row.method=='oidc+2fa'


def test_group_policy_verified_email_and_userinfo_subject(db,provider):
    for changes in ({'groups':['stranger']},{'email_verified':False}):
        with pytest.raises(HTTPException):oidc.claims_policy(provider['cfg'],{**provider['claims'],**changes})
    c=client();state=begin(c,provider);provider['info']={'sub':'another-subject'}
    assert callback(c,state).headers['location']=='/login' and not db.scalar(select(OidcIdentity.id))


def test_signed_backchannel_only_matching_oidc_sessions_and_replay(db,provider):
    c=client();state=begin(c,provider);callback(c,state);identity=db.scalar(select(OidcIdentity));user=db.get(User,identity.user_id)
    local=UserSession(user_id=user.id,sid_hash=secrets.token_hex(32),method='password');db.add(local);db.commit()
    claims={'iss':provider['cfg']['issuer'],'aud':'portal-client','iat':int(time.time()),'jti':'logout-1','sub':identity.subject,'sid':provider['claims']['sid'],'events':{'http://schemas.openid.net/event/backchannel-logout':{}}}
    token=jwt.encode(claims,provider['key'],algorithm='RS256',headers={'kid':'test-key'})
    assert client().post('/auth/oidc/backchannel',data={'logout_token':token}).status_code==200
    assert db.scalar(select(UserSession.id).where(UserSession.oidc_identity_id==identity.id)) is None
    assert db.get(UserSession,local.id)
    assert client().post('/auth/oidc/backchannel',data={'logout_token':token}).status_code==200
    bad={**claims,'jti':'logout-2','nonce':'forbidden'}
    with pytest.raises(HTTPException):oidc.verify_token(provider['cfg'],provider['doc'],jwt.encode(bad,provider['key'],algorithm='RS256',headers={'kid':'test-key'}),logout=True)


def test_token_alg_audience_and_endpoint_guards(provider):
    claims={**provider['claims'],'nonce':'x'}
    for token in [jwt.encode(claims,'x'*40,algorithm='HS256'),jwt.encode({**claims,'aud':'wrong'},provider['key'],algorithm='RS256',headers={'kid':'test-key'})]:
        with pytest.raises(HTTPException):oidc.verify_token(provider['cfg'],provider['doc'],token,oidc.digest('x'))
    with pytest.raises(HTTPException):oidc.endpoint(provider['cfg'],'https://evil.example.org/token')
    with pytest.raises(HTTPException):oidc.url('http://cloud.example.org')


def test_admin_settings_csrf_connection_test_and_secret_not_rendered(db,provider):
    c=login('admin@example.org','admin-passwort-123');page=c.get('/admin/oidc');assert page.status_code==200
    assert 'test-client-secret' not in page.text
    assert c.post('/admin/oidc',data={'action':'disable'}).status_code==400
    assert c.post('/admin/oidc',data={'csrf':csrf_of(page.text),'action':'disable'}).status_code==303
    assert not oidc.usable(oidc.config(db))
    assert 'Mit Nextcloud anmelden' not in client().get('/login').text
    user=User(email='limited-'+provider['suffix']+'@example.org',name='Limited',password_hash=hash_password('passwort-test-123'),permissions='');db.add(user);db.commit()
    assert login(user.email,'passwort-test-123').get('/admin/oidc').status_code==403


def test_admin_can_test_enable_and_retain_encrypted_secret(db,provider):
    c=login('admin@example.org','admin-passwort-123');page=c.get('/admin/oidc')
    data={'csrf':csrf_of(page.text),'provider':'nextcloud','base_url':provider['cfg']['base_url'],
          'client_id':'portal-client','hours':'8','group_claim':'groups','allowed_groups':'employees',
          'auto_create':'1','require_verified_email':'1','sync_name':'1','sync_email':'1','backchannel':'1',
          'central_logout':'1','enabled':'1','action':'test'}
    assert c.post('/admin/oidc',data=data).status_code==303
    cfg=oidc.config(db);assert oidc.usable(cfg) and cfg['issuer']==provider['cfg']['issuer']
    assert cfg['client_secret_enc']==provider['cfg']['client_secret_enc']
    assert cfg['metadata']['end_session_endpoint']==provider['doc']['end_session_endpoint']
    data.update(action='save',client_id='unverified-client',issuer=cfg['issuer'])
    assert c.post('/admin/oidc',data=data).status_code==422
    assert oidc.config(db)['client_id']=='portal-client'


def test_first_local_password_and_safe_unlink(db,provider):
    c=client();callback(c,begin(c,provider));identity=db.scalar(select(OidcIdentity));user=db.get(User,identity.user_id)
    page=c.get('/profile/identity');csrf=csrf_of(page.text)
    assert c.post(f'/profile/identity/{identity.id}/unlink',data={'csrf':csrf}).status_code==409
    page=c.get('/profile');assert page.status_code==200
    assert c.post('/profile',data={'csrf':csrf_of(page.text),'name':user.name,'new_password':'new-local-password-123'}).status_code==303
    db.refresh(user);assert user.password_set
    assert login(user.email,'new-local-password-123').get('/profile').status_code==200
    assert c.post(f'/profile/identity/{identity.id}/unlink',data={'csrf':csrf}).status_code==303
    assert db.scalar(select(OidcIdentity.id).where(OidcIdentity.id==identity.id)) is None
    assert c.get('/profile').status_code==303
    assert login(user.email,'new-local-password-123').get('/profile').status_code==200


def test_provider_outage_never_prevents_local_logout(db,provider,monkeypatch):
    c=client();callback(c,begin(c,provider));identity=db.scalar(select(OidcIdentity))
    page=c.get('/profile')
    def unavailable(cfg):raise HTTPException(503,'offline')
    monkeypatch.setattr(oidc,'discovery',unavailable)
    response=c.post('/auth/oidc/logout',data={'csrf':csrf_of(page.text)})
    assert response.status_code==303 and response.headers['location']=='/login'
    assert not db.scalar(select(UserSession.id).where(UserSession.oidc_identity_id==identity.id))
    assert c.get('/profile').status_code==303


def test_group_from_another_identity_and_voluntary_profile_are_preserved(db,provider):
    from app import profiles
    g=Group(name='shared-'+provider['suffix']);db.add(g);db.commit()
    cfg={**provider['cfg'],'group_map':{'employees':g.id},'profile_map':{'department':'department'}}
    identity,user=oidc.identify(db,cfg,provider['claims']);db.flush()
    user.profile_data_enc=profiles.store({'prefill_enabled':True,'home_city':'Otterberg'})
    other=OidcIdentity(user_id=user.id,issuer='https://other.example.org',subject='other-'+provider['suffix']);db.add(other);db.flush()
    db.add(OidcGroupGrant(identity_id=other.id,group_id=g.id));db.commit()
    oidc.sync(db,{**cfg,'allowed_groups':[]},identity,{**provider['claims'],'groups':[],'department':'Personal'});db.commit()
    assert db.get(GroupMember,(g.id,user.id)) and not db.get(OidcGroupGrant,(identity.id,g.id))
    assert profiles.read(user)=={'prefill_enabled':True,'home_city':'Otterberg','department':'Personal'}


def test_disabled_provider_blocks_pending_mfa(db,provider):
    identity,user=oidc.identify(db,provider['cfg'],provider['claims']);secret=twofa.new_secret();twofa.enable_totp(user,secret)
    set_setting(db,'mfa_totp_allowed','1');set_setting(db,'mfa_required','off');db.commit()
    c=client();assert callback(c,begin(c,provider)).headers['location']=='/login/2fa'
    page=c.get('/login/2fa');cfg=oidc.config(db);cfg['enabled']=False;set_setting(db,'oidc_config',json.dumps(cfg));db.commit()
    response=c.post('/login/2fa',data={'csrf':csrf_of(page.text),'method':'totp','code':twofa.totp_now(secret)})
    assert response.status_code==403
    assert not db.scalar(select(UserSession.id).where(UserSession.user_id==user.id))
