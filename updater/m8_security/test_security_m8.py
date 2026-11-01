"""M8 full PostgreSQL authorization regressions – isolated test DB ONLY."""
from uuid import uuid4

from sqlalchemy import select
from app.db import SessionLocal
from app.main import app, current_user
from app.models import User, Project, ProjectMember, Task


def mutation(entity, eid, fields, version=0, operation='upsert'):
    return {'mutation_id':str(uuid4()),'entity_type':entity,'operation':operation,
            'entity_id':eid,'base_version':version,'data':fields}


def push(client,headers,items):
    response=client.post('/sync/push',headers=headers,json={'mutations':items})
    assert response.status_code==200,response.text
    return response.json()['results']


def project(client,headers,name='M8 sample'):
    eid=str(uuid4())
    assert push(client,headers,[mutation('project',eid,{'name':name})])[0]['status']=='applied'
    return eid


def person(role='worker'):
    with SessionLocal() as db:
        u=User(email=f'm8-{uuid4().hex}@example.com',name='M8 user',role=role,active=True,password_hash='no-login')
        db.add(u);db.commit();return u.id


class Actor:
    def __init__(self, uid):self.uid=uid
    def __enter__(self):
        def actor():
            with SessionLocal() as db:return db.get(User,self.uid)
        app.dependency_overrides[current_user]=actor
        return self
    def __exit__(self,*_):app.dependency_overrides.pop(current_user,None)


def test_viewer_cannot_create_root_project_or_child_task_or_comment(client,auth_headers):
    pid=project(client,auth_headers)
    uid=person()
    with SessionLocal() as db:
        db.add(ProjectMember(project_id=pid,user_id=uid,role='viewer'));db.commit()
    with Actor(uid):
        root=str(uuid4())
        result=push(client,{},[mutation('project',root,{'name':'Privilege escalation'})])[0]
        assert result['status']=='rejected'
        assert 'rendszergazda' in result['detail']
        assert push(client,{},[mutation('project',str(uuid4()),{'name':'Illegitimate child','parent_id':pid})])[0]['status']=='rejected'
        assert push(client,{},[mutation('task',str(uuid4()),{'project_id':pid,'title':'Illegitimate'})])[0]['status']=='rejected'
        assert client.get(f'/team/projects/{pid}/members').status_code==200
        assert client.post(f'/team/projects/{pid}/members',json={'email':'other@example.com','role':'owner'}).status_code==403
        assert client.post(f'/plans/{pid}',data={'name':'bad','revision':'v1'},files={'upload':('a.pdf',b'fake','application/pdf')}).status_code==403
    with SessionLocal() as db:assert db.get(Project,root) is None


def test_editor_cannot_create_root_but_can_create_writable_child(client,auth_headers):
    pid=project(client,auth_headers)
    uid=person()
    with SessionLocal() as db:
        db.add(ProjectMember(project_id=pid,user_id=uid,role='editor'));db.commit()
    with Actor(uid):
        assert push(client,{},[mutation('project',str(uuid4()),{'name':'Denied root'})])[0]['status']=='rejected'
        child=str(uuid4())
        assert push(client,{},[mutation('project',child,{'name':'Allowed child','parent_id':pid})])[0]['status']=='applied'
        task=str(uuid4())
        assert push(client,{},[mutation('task',task,{'project_id':pid,'title':'Allowed task'})])[0]['status']=='applied'
        assert client.post(f'/team/projects/{pid}/members',json={'email':'none@example.com','role':'viewer'}).status_code==403


def test_admin_recovers_preexisting_private_project_without_rewriting_owner(client,auth_headers):
    uid=person()
    pid=str(uuid4());tid=str(uuid4())
    with SessionLocal() as db:
        db.add(Project(id=pid,name='Legacy private',description='',created_by_id=uid))
        db.add(ProjectMember(project_id=pid,user_id=uid,role='owner'))
        db.add(Task(id=tid,project_id=pid,title='Existing task'))
        db.commit()
    # Admin has no membership to this legacy project: recovery must never fabricate one.
    read=client.get(f'/team/projects/{pid}/members',headers=auth_headers)
    assert read.status_code==200,read.text
    assert read.json()['can_manage'] is True
    assert any(x['id']==uid and x['role']=='owner' for x in read.json()['members'])
    data=client.get('/team/directory',headers=auth_headers)
    assert data.status_code==200
    assert any(pid in x['project_ids'] for x in data.json()['users'] if x['id']==uid)
    assert client.get('/sync/access-scope',headers=auth_headers).status_code==200
    # With a legacy unlogged project, can_read_project still supports document endpoints and team routes.
    with SessionLocal() as db:
        assert db.get(ProjectMember,(pid,db.scalar(select(User.id).where(User.email=='admin@example.com')))) is None
        assert db.get(Project,pid).created_by_id==uid
        assert db.get(Task,tid).project_id==pid


def test_scope_detects_membership_grant_role_change_revoke(client,auth_headers):
    pid=project(client,auth_headers)
    uid=person()
    with Actor(uid):
        before=client.get('/sync/access-scope').json()
        assert before['project_count']==0
        assert client.get('/sync/pull?cursor=0').json()['changes']==[]
    with SessionLocal() as db:
        db.add(ProjectMember(project_id=pid,user_id=uid,role='viewer'));db.commit()
    with Actor(uid):
        viewer=client.get('/sync/access-scope').json()
        assert viewer['fingerprint']!=before['fingerprint']
        # On scope change, a full cursor=0 backfill finds earlier changes.
        assert any(x['entity_id']==pid for x in client.get('/sync/pull?cursor=0').json()['changes'])
    with SessionLocal() as db:
        db.get(ProjectMember,(pid,uid)).role='editor';db.commit()
    with Actor(uid):
        editor=client.get('/sync/access-scope').json()
        assert editor['fingerprint']!=viewer['fingerprint']
    with SessionLocal() as db:
        db.delete(db.get(ProjectMember,(pid,uid)));db.commit()
    with Actor(uid):
        revoked=client.get('/sync/access-scope').json()
        assert revoked['fingerprint']!=editor['fingerprint']
        assert client.get('/sync/pull?cursor=0').json()['changes']==[]


def test_nonmember_cannot_read_members_or_modify_any_parent(client,auth_headers):
    pid=project(client,auth_headers)
    outsider=person()
    with Actor(outsider):
        assert client.get(f'/team/projects/{pid}/members').status_code==403
        assert push(client,{},[mutation('project',str(uuid4()),{'name':'Illegal','parent_id':pid})])[0]['status']=='rejected'
        assert push(client,{},[mutation('task',str(uuid4()),{'project_id':pid,'title':'Illegal'})])[0]['status']=='rejected'


def test_inactive_system_admin_is_not_allowed_by_role_flag(client,auth_headers):
    pid=project(client,auth_headers)
    uid=person('admin')
    with SessionLocal() as db:
        u=db.get(User,uid);u.active=False;db.commit()
    from app.main import can_read_project,can_write_project
    with SessionLocal() as db:
        assert can_read_project(db,pid,uid) is False
        assert can_write_project(db,pid,uid) is False
