"""M7: video files through existing project documents, with membership-deny regressions.
Runs ONLY in isolated PostgreSQL CI. No real user accounts, attachments or prod DB.
"""
from uuid import uuid4
from pathlib import Path
from io import BytesIO
import struct
import pytest
from sqlalchemy import select
from fastapi import HTTPException

from app.main import app, validate_video_header
from app import main as main_module
from app.db import SessionLocal
from app.models import Plan, ProjectMember, User

MP4 = struct.pack('>I', 24) + b'ftypisom' + b'\0\0\0\0isommp42' + b'\0\0\0\x08mdat'
WEBM = bytes.fromhex('1a45dfa3') + b'\x89\x42\x82\x84webm' + b'\x18\x53\x80\x67'

def project(client, auth_headers):
    ident = str(uuid4())
    response = client.post('/sync/push', headers=auth_headers, json={'mutations':[{
        'mutation_id':str(uuid4()), 'entity_type':'project', 'operation':'upsert',
        'entity_id':ident,'base_version':0,'data':{'name':'M7 elkülönített teszt'}
    }]})
    assert response.status_code == 200, response.text
    assert response.json()['results'][0]['status']=='applied'
    return ident

def post_media(client, headers, project_id, data, mime, filename='m7-film.mp4'):
    return client.post(f'/plans/{project_id}', headers=headers,
        data={'name':'Biztonságos próba','revision':'v1','description':'M7 video'},
        files={'upload':(filename,data,mime)})

def test_valid_mp4_project_document_and_authenticated_download(client,auth_headers):
    project_id=project(client,auth_headers)
    r=post_media(client,auth_headers,project_id,MP4,'video/mp4')
    assert r.status_code==200,r.text
    out=r.json()
    assert out['mime_type']=='video/mp4' and out['page_count'] is None
    assert out['file_size']==len(MP4)
    assert client.get(f'/plans/{out["id"]}/content').status_code==401
    downloaded=client.get(f'/plans/{out["id"]}/content',headers=auth_headers)
    assert downloaded.status_code==200 and downloaded.content==MP4
    assert downloaded.headers['content-type'].startswith('video/mp4')


def test_valid_webm_project_document(client,auth_headers):
    p=project(client,auth_headers)
    r=post_media(client,auth_headers,p,WEBM,'video/webm','movie.webm')
    assert r.status_code==200,r.text
    assert r.json()['mime_type']=='video/webm'


@pytest.mark.parametrize('data,mime',[
    (b'%PDF-1.4\nnot a video','video/mp4'),
    (b'broken','video/webm'),
    (MP4,'video/webm'),
])
def test_fake_media_rejected_and_does_not_persist(client,auth_headers,data,mime):
    p=project(client,auth_headers)
    response=post_media(client,auth_headers,p,data,mime)
    assert response.status_code==415,response.text
    with SessionLocal() as db:
        assert list(db.scalars(select(Plan).where(Plan.project_id==p)))==[]


def test_video_limit_only_video_not_all_documents(client,auth_headers,monkeypatch):
    p=project(client,auth_headers)
    monkeypatch.setattr(main_module,'VIDEO_MAX_UPLOAD_BYTES',16)
    assert post_media(client,auth_headers,p,MP4,'video/mp4').status_code==413


def test_viewer_can_download_but_cannot_upload_or_modify(client,auth_headers):
    p=project(client,auth_headers)
    r=post_media(client,auth_headers,p,MP4,'video/mp4')
    assert r.status_code==200,r.text
    did=r.json()['id']
    with SessionLocal() as db:
        viewer=User(email=f'viewer-{uuid4().hex}@example.com',name='Viewer',role='worker',active=True,password_hash='no-login-used')
        db.add(viewer);db.flush()
        viewer_id=viewer.id
        db.add(ProjectMember(project_id=p,user_id=viewer_id,role='viewer'))
        db.commit()
    from app.main import current_user
    def viewer_actor():
        with SessionLocal() as db:
            return db.get(User,viewer_id)
    app.dependency_overrides[current_user]=viewer_actor
    try:
        assert client.get(f'/plans/{did}/content').status_code==200
        assert post_media(client,{},p,MP4,'video/mp4').status_code==403
        update=client.post('/sync/push',json={'mutations':[{
            'mutation_id':str(uuid4()),'entity_type':'project','operation':'upsert',
            'entity_id':p,'base_version':1,'data':{'name':'Unauthorized'}
        }]})
        assert update.status_code==200
        assert update.json()['results'][0]['status']=='rejected'
        assert client.post(f'/team/projects/{p}/members',json={'email':'nonexistent@example.com','role':'owner'}).status_code==403
    finally:
        app.dependency_overrides.pop(current_user,None)


def test_video_header_validation_is_bounded(tmp_path):
    f=tmp_path/'x.mp4';f.write_bytes(MP4)
    validate_video_header(f,'video/mp4')
    f.write_bytes(b'\x00\x00\x00\x18bad!isom')
    with pytest.raises(HTTPException) as e:
        validate_video_header(f,'video/mp4')
    assert e.value.status_code==415
