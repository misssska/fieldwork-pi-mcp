"""M4 project membership access and assignee security contract."""
from uuid import uuid4
from sqlalchemy import select
from app.db import SessionLocal
from app.models import User, Project, ProjectMember


def create_project(client, headers):
    ident = str(uuid4())
    response = client.post('/sync/push', headers=headers, json={'mutations': [{
        'mutation_id': str(uuid4()), 'entity_type': 'project', 'operation': 'upsert',
        'entity_id': ident, 'base_version': 0, 'data': {'name': 'M4 próba'}
    }]})
    assert response.status_code == 200, response.text
    assert response.json()['results'][0]['status'] == 'applied'
    return ident


def test_project_scoped_member_listing_and_last_owner(client, auth_headers):
    project_id = create_project(client, auth_headers)
    result = client.get(f'/team/projects/{project_id}/members', headers=auth_headers)
    assert result.status_code == 200, result.text
    data = result.json()
    assert data['can_manage'] is True
    assert len(data['members']) == 1
    admin = data['members'][0]
    assert admin['role'] == 'owner'
    assert admin['email'] == 'admin@example.com'
    directory = client.get('/team/directory', headers=auth_headers)
    assert directory.status_code == 200
    assert project_id in directory.json()['users'][0]['project_ids']
    change = client.patch(f'/team/projects/{project_id}/members/{admin["id"]}',
                          headers=auth_headers, json={'role': 'viewer'})
    assert change.status_code == 409
    removed = client.delete(f'/team/projects/{project_id}/members/{admin["id"]}', headers=auth_headers)
    assert removed.status_code == 409
    duplicate = client.post(f'/team/projects/{project_id}/members', headers=auth_headers,
                            json={'email': 'admin@example.com', 'role': 'editor'})
    assert duplicate.status_code == 409


def test_unshared_and_unknown_projects_do_not_leak_members(client, auth_headers):
    project_id = create_project(client, auth_headers)
    with SessionLocal() as db:
        uid = db.scalar(select(User.id).where(User.email == 'admin@example.com'))
        db.delete(db.get(ProjectMember, (project_id, uid)))
        db.commit()
    assert client.get(f'/team/projects/{project_id}/members', headers=auth_headers).status_code == 403
    assert client.post(f'/team/projects/{project_id}/members', headers=auth_headers,
        json={'email':'admin@example.com','role':'owner'}).status_code == 403
    assert client.get(f'/team/projects/{uuid4()}/members', headers=auth_headers).status_code == 404


def test_invalid_task_assignee_is_rejected(client, auth_headers):
    project_id = create_project(client, auth_headers)
    payload = {'mutations': [{
        'mutation_id': str(uuid4()), 'entity_type': 'task', 'operation': 'upsert',
        'entity_id': str(uuid4()), 'base_version': 0,
        'data': {'project_id':project_id,'title':'Kiosztási próba','assigned_user_id': str(uuid4())}
    }]}
    response = client.post('/sync/push', headers=auth_headers, json=payload)
    assert response.status_code == 200
    assert response.json()['results'][0]['status'] == 'rejected'
    assert 'felelős' in response.json()['results'][0]['detail']
    with SessionLocal() as db:
        uid = db.scalar(select(User.id).where(User.email == 'admin@example.com'))
    payload['mutations'][0]['mutation_id'] = str(uuid4())
    payload['mutations'][0]['data']['assigned_user_id'] = uid
    response = client.post('/sync/push', headers=auth_headers, json=payload)
    assert response.status_code == 200
    assert response.json()['results'][0]['status'] == 'applied'
