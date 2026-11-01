"""M8 dedicated PostgreSQL-only integration tests; include in isolated server/tests.

The existing server/tests/conftest.py MUST enforce an ephemeral destructive-test DB.
"""
from uuid import uuid4
from sqlalchemy import select
from app.db import SessionLocal
from app.main import app, current_user
from app.models import ProjectMember, Task, User


def create_project(client, headers):
    project_id = str(uuid4())
    response = client.post('/sync/push', headers=headers, json={'mutations': [{
        'mutation_id':str(uuid4()), 'entity_type':'project', 'operation':'upsert',
        'entity_id':project_id, 'base_version':0, 'data':{'name':'M8 shared project'}}]})
    assert response.status_code == 200 and response.json()['results'][0]['status']=='applied'
    return project_id


def new_user(role='worker'):
    with SessionLocal() as db:
        person = User(email=f'm8-{uuid4().hex}@example.test', name='M8 Teszt',
                      role=role, active=True, password_hash='disabled-test-hash')
        db.add(person); db.commit(); return person.id


class Actor:
    def __init__(self, ident): self.ident=ident
    def __enter__(self):
        def actor():
            with SessionLocal() as db: return db.get(User,self.ident)
        app.dependency_overrides[current_user]=actor
        return self
    def __exit__(self,*_):app.dependency_overrides.pop(current_user,None)


def test_owner_can_search_and_add_by_user_id(client,auth_headers):
    project_id=create_project(client,auth_headers)
    ident=new_user()
    res=client.get(f'/team/projects/{project_id}/candidates',headers=auth_headers)
    assert res.status_code==200 and any(p['id']==ident for p in res.json()['users'])
    added=client.post(f'/team/projects/{project_id}/members',headers=auth_headers,
                      json={'user_id':ident,'role':'viewer'})
    assert added.status_code==201 and added.json()['role']=='viewer'
    assert client.post(f'/team/projects/{project_id}/members',headers=auth_headers,
                       json={'user_id':ident,'role':'viewer'}).status_code==409
    assert all(p['id']!=ident for p in client.get(f'/team/projects/{project_id}/candidates',headers=auth_headers).json()['users'])


def test_unauthorized_candidate_directory_and_promotion_blocked(client,auth_headers):
    pid=create_project(client,auth_headers)
    outsider=new_user()
    with Actor(outsider):
        assert client.get(f'/team/projects/{pid}/candidates').status_code==403
        assert client.patch(f'/team/accounts/{outsider}/role',json={'role':'editor'}).status_code==403


def test_global_editor_reads_all_but_cannot_mutate_unshared_project(client,auth_headers):
    pid=create_project(client,auth_headers)
    tid=str(uuid4())
    result=client.post('/sync/push',headers=auth_headers,json={'mutations':[{
        'mutation_id':str(uuid4()), 'entity_type':'task', 'operation':'upsert',
        'entity_id':tid, 'base_version':0, 'data':{'project_id':pid,'title':'Látható feladat'}}]})
    assert result.json()['results'][0]['status']=='applied'
    uid=new_user()
    promotion=client.patch(f'/team/accounts/{uid}/role',headers=auth_headers,json={'role':'editor'})
    assert promotion.status_code==200 and promotion.json()['role']=='editor'
    with Actor(uid):
        changes=client.get('/sync/pull?cursor=0').json()['changes']
        assert {pid,tid} <= {x['entity_id'] for x in changes}
        denied=client.post('/sync/push',json={'mutations':[{
            'mutation_id':str(uuid4()),'entity_type':'task','operation':'upsert',
            'entity_id':tid,'base_version':1,'data':{'title':'Nincs írásjog'}}]})
        assert denied.status_code==200 and denied.json()['results'][0]['status']=='rejected'
        assert client.post(f'/team/projects/{pid}/members',json={'user_id':uid,'role':'owner'}).status_code==403
    with SessionLocal() as db:
        assert db.get(ProjectMember,(pid,uid)) is None
        assert db.get(Task,tid).title=='Látható feladat'


def test_global_role_cannot_escalate_to_admin(client,auth_headers):
    with SessionLocal() as db:
        aid=db.scalar(select(User.id).where(User.email=='admin@example.com'))
    assert client.patch(f'/team/accounts/{aid}/role',headers=auth_headers,json={'role':'worker'}).status_code==403
    uid=new_user()
    assert client.patch(f'/team/accounts/{uid}/role',headers=auth_headers,json={'role':'admin'}).status_code==422


def test_scope_changes_for_global_role_and_revocation(client, auth_headers):
    pid = create_project(client, auth_headers)
    uid = new_user()
    with Actor(uid):
        before = client.get('/sync/access-scope').json()['fingerprint']
        assert not any(x['entity_id'] == pid for x in client.get('/sync/pull?cursor=0').json()['changes'])
    assert client.patch(f'/team/accounts/{uid}/role', headers=auth_headers,
                        json={'role':'editor'}).status_code == 200
    with Actor(uid):
        after_grant = client.get('/sync/access-scope').json()['fingerprint']
        assert before != after_grant
        assert pid in {x['entity_id'] for x in client.get('/sync/pull?cursor=0').json()['changes']}
    assert client.patch(f'/team/accounts/{uid}/role', headers=auth_headers,
                        json={'role':'worker'}).status_code == 200
    with Actor(uid):
        after_revoke = client.get('/sync/access-scope').json()['fingerprint']
        assert after_revoke == before
        assert not any(x['entity_id'] == pid for x in client.get('/sync/pull?cursor=0').json()['changes'])


def test_membership_scope_grant_and_revoke_including_existing_records(client, auth_headers):
    pid = create_project(client, auth_headers)
    tid = str(uuid4())
    created = client.post('/sync/push', headers=auth_headers, json={'mutations':[{
        'mutation_id':str(uuid4()), 'entity_type':'task', 'operation':'upsert',
        'entity_id':tid, 'base_version':0, 'data':{'project_id':pid,'title':'Korábbi munka'}
    }]}).json()['results'][0]
    assert created['status']=='applied'
    uid = new_user()
    with Actor(uid):
        before = client.get('/sync/access-scope').json()['fingerprint']
        assert client.get('/sync/pull?cursor=0').json()['changes'] == []
    assert client.post(f'/team/projects/{pid}/members',headers=auth_headers,
                       json={'user_id':uid,'role':'viewer'}).status_code==201
    with Actor(uid):
        after = client.get('/sync/access-scope').json()['fingerprint']
        assert after != before
        assert {pid,tid} <= {x['entity_id'] for x in client.get('/sync/pull?cursor=0').json()['changes']}
        assert client.post('/sync/push',json={'mutations':[{
            'mutation_id':str(uuid4()),'entity_type':'task','operation':'upsert',
            'entity_id':tid,'base_version':1,'data':{'title':'Tiltott viewer módosítás'}
        }]}).json()['results'][0]['status']=='rejected'
    assert client.delete(f'/team/projects/{pid}/members/{uid}',headers=auth_headers).status_code==204
    with Actor(uid):
        assert client.get('/sync/access-scope').json()['fingerprint']==before
        assert client.get('/sync/pull?cursor=0').json()['changes']==[]
        assert client.get(f'/team/projects/{pid}/members').status_code==403
    with SessionLocal() as db:
        assert db.get(Task,tid).title=='Korábbi munka'
