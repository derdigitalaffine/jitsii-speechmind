"""POI settings and server-side route calculation shared by all form modules."""
import json
from urllib.parse import urlparse
from fastapi import Depends, HTTPException, Request, UploadFile, File
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse, Response
from sqlalchemy import select
from . import locations, routing
from .db import PortalLocation, LocationFavorite, Group, get_settings, set_setting
from .main import app, current_user, admin_user, session_user, get_db, check_csrf, flash, redirect, render, rate_limit, csrf_valid


def manage(db,user):
    if not locations.can_manage(db,user):
        raise HTTPException(403,'Keine Berechtigung zur Pflege zentraler Orte.')


@app.get('/settings/locations')
def location_page(request:Request,user=Depends(current_user),db=Depends(get_db)):
    return render(request,'locations.html',user,locations=locations.visible(db,user),can_manage=locations.can_manage(db,user),
                  cfg=get_settings(db),groups=list(db.scalars(select(Group).order_by(Group.name))),
                  favorites=set(db.scalars(select(LocationFavorite.location_id).where(LocationFavorite.user_id==user.id))))


@app.post('/settings/locations/save',dependencies=[Depends(check_csrf)])
async def location_save(request:Request,user=Depends(current_user),db=Depends(get_db)):
    raw=await request.form()
    lid=str(raw.get('id') or '')
    location=db.get(PortalLocation,int(lid)) if lid.isdigit() else None
    personal=raw.get('personal')=='1'
    if location:
        if location.owner_id is None:
            manage(db,user)
        elif location.owner_id!=user.id:
            raise HTTPException(404)
    elif not personal:
        manage(db,user)
    try:
        values=locations.clean(raw)
    except ValueError as exc:
        flash(request,str(exc),'error');return redirect('/settings/locations')
    if location is None:
        location=PortalLocation(owner_id=user.id if personal else None,**values);db.add(location)
    else:
        for key,value in values.items():setattr(location,key,value)
    location.active=True
    db.commit();flash(request,'Ort gespeichert.');return redirect('/settings/locations')


@app.post('/settings/locations/{lid:int}/remove',dependencies=[Depends(check_csrf)])
def location_remove(lid:int,request:Request,user=Depends(current_user),db=Depends(get_db)):
    loc=db.get(PortalLocation,lid)
    if loc is None or (loc.owner_id is not None and loc.owner_id!=user.id):raise HTTPException(404)
    if loc.owner_id is None:manage(db,user)
    loc.active=False;db.commit();return redirect('/settings/locations')


@app.post('/settings/locations/{lid:int}/favorite',dependencies=[Depends(check_csrf)])
def location_favorite(lid:int,request:Request,user=Depends(current_user),db=Depends(get_db)):
    if lid not in {x.id for x in locations.visible(db,user)}:raise HTTPException(404)
    favorite=db.get(LocationFavorite,(user.id,lid))
    if favorite:db.delete(favorite)
    else:db.add(LocationFavorite(user_id=user.id,location_id=lid))
    db.commit();return redirect('/settings/locations')


@app.get('/settings/locations/export.csv')
def location_export(request:Request,user=Depends(current_user),db=Depends(get_db)):
    return Response(locations.export(locations.visible(db,user)),media_type='text/csv; charset=utf-8',
                    headers={'Content-Disposition':'attachment; filename="Orte.csv"','Cache-Control':'no-store'})


@app.post('/settings/locations/import',dependencies=[Depends(check_csrf)])
async def location_import(request:Request,file:UploadFile=File(...),user=Depends(current_user),db=Depends(get_db)):
    raw=await request.form();personal=raw.get('personal')=='1'
    if not personal:manage(db,user)
    try:
        count=locations.import_rows(db,await file.read(2*1024*1024+1),user.id if personal else None)
        db.commit();flash(request,f'{count} Orte importiert.')
    except ValueError as exc:
        db.rollback();flash(request,str(exc),'error')
    return redirect('/settings/locations')


@app.post('/settings/locations/seed',dependencies=[Depends(check_csrf)])
def location_seed(request:Request,user=Depends(current_user),db=Depends(get_db)):
    manage(db,user);count=locations.seed_offices(db);db.commit();flash(request,f'{count} Rathäuser angelegt. Bitte Koordinaten prüfen.');return redirect('/settings/locations')


@app.post('/settings/locations/services',dependencies=[Depends(check_csrf)])
async def location_services(request:Request,user=Depends(admin_user),db=Depends(get_db)):
    data=await request.form()
    urls={key:str(data.get('routing_'+key+'_url') or default).strip().rstrip('/') for key,default in routing.DEFAULTS.items()}
    for url in urls.values():
        parsed=urlparse(url)
        if parsed.scheme not in ('https','http') or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
            flash(request,'Bitte gültige Dienstadressen ohne Zugangsdaten angeben.','error');return redirect('/settings/locations')
    for key,url in urls.items():set_setting(db,'routing_'+key+'_url',url[:500])
    set_setting(db,'routing_auto','1' if data.get('routing_auto')=='1' else '0')
    groups={str(g.id) for g in db.scalars(select(Group))}
    set_setting(db,'location_manager_groups',','.join(x for x in data.getlist('manager_groups') if x in groups))
    db.commit();flash(request,'Dienste und Pflegeberechtigungen gespeichert.');return redirect('/settings/locations')


@app.get('/geo/locations')
def location_options(request:Request,db=Depends(get_db)):
    user=session_user(request,db)
    favorites=set(db.scalars(select(LocationFavorite.location_id).where(LocationFavorite.user_id==user.id))) if user else set()
    return JSONResponse({'locations':[locations.data(p)|{'label':locations.label(p),'favorite':p.id in favorites} for p in locations.visible(db,user)],
                         'routing_auto':get_settings(db).get('routing_auto','1')=='1',
                         'categories':{k:v[0] for k,v in routing.CATEGORIES.items()},
                         'public_routing':{k:routing.public_service(v) for k,v in routing.config().items()}},headers={'Cache-Control':'no-store'})


@app.post('/geo/route')
async def route_quote(request:Request):
    if not csrf_valid(request.session,request.headers.get('X-CSRF-Token')):
        raise HTTPException(400,'Sitzung abgelaufen. Bitte Seite neu laden.')
    rate_limit(request,'route',limit=30,window=60)
    raw=await request.body()
    if len(raw)>20000:raise HTTPException(413,'Zu viele Streckenpunkte.')
    try:
        data=json.loads(raw)
        if not isinstance(data,dict) or not isinstance(data.get('points'),list):raise ValueError('Ungültige Punkte.')
        result=await run_in_threadpool(routing.quote,data['points'],str(data.get('category') or ''),data.get('public_points') is True)
    except (ValueError,TypeError) as exc:
        raise HTTPException(400,str(exc)) from None
    return JSONResponse(result,headers={'Cache-Control':'no-store'})
