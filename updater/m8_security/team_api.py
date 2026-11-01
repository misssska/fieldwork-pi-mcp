"""FieldWork M4: project-scoped team directory and membership operations.

Register from app.main after current_user and can_read_project are defined.
No database migration, account creation, password or secret handling.
"""
from fastapi import Depends, HTTPException
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select
from sqlalchemy.orm import Session
from .db import get_db
from .models import Project, ProjectMember, User

ROLES = {'owner', 'editor', 'viewer'}


class MembershipIn(BaseModel):
    email: EmailStr
    role: str = Field(pattern='^(owner|editor|viewer)$')


class RoleIn(BaseModel):
    role: str = Field(pattern='^(owner|editor|viewer)$')


def register_team_routes(app, current_user, can_read_project):
    def project_or_404(db, project_id):
        project = db.get(Project, project_id)
        if project is None or project.deleted:
            raise HTTPException(404, 'A projekt nem található')
        return project

    def require_read(db, project_id, user):
        project_or_404(db, project_id)
        if not can_read_project(db, project_id, user.id):
            raise HTTPException(403, 'Nincs hozzáférésed ehhez a projekthez')

    def is_manager(db, project_id, user):
        membership = db.get(ProjectMember, (project_id, user.id))
        return bool(membership and membership.role == 'owner')

    def require_manager(db, project_id, user):
        require_read(db, project_id, user)
        if not is_manager(db, project_id, user):
            raise HTTPException(403, 'Csak projektgazda módosíthatja a tagságot')

    def members_with_lock(db, project_id):
        return list(db.scalars(select(ProjectMember).where(ProjectMember.project_id == project_id)
                               .order_by(ProjectMember.user_id).with_for_update()))

    def protect_last_owner(members, target, next_role):
        if target.role == 'owner' and next_role != 'owner':
            if sum(1 for item in members if item.role == 'owner') <= 1:
                raise HTTPException(409, 'A projekt utolsó gazdája nem távolítható el')

    def row(member, user):
        return {'id': user.id, 'name': user.name, 'email': user.email,
                'system_role': user.role, 'active': user.active, 'role': member.role}

    @app.get('/team/directory')
    def directory(user: User = Depends(current_user), db: Session = Depends(get_db)):
        project_ids = set(db.scalars(select(ProjectMember.project_id)
            .join(Project, Project.id == ProjectMember.project_id)
            .where(ProjectMember.user_id == user.id, Project.deleted.is_(False))))
        memberships = list(db.scalars(select(ProjectMember)
            .join(Project, Project.id == ProjectMember.project_id)
            .where(ProjectMember.project_id.in_(project_ids), Project.deleted.is_(False)))) if project_ids else []
        visible_ids = {member.user_id for member in memberships}
        if user.role == 'admin':
            people = list(db.scalars(select(User).where(User.active.is_(True)).order_by(User.name)))
        else:
            people = list(db.scalars(select(User).where(User.id.in_(visible_ids), User.active.is_(True)).order_by(User.name))) if visible_ids else []
        by_user = {}
        for member in memberships:
            by_user.setdefault(member.user_id, set()).add(member.project_id)
        return {'users': [{'id': person.id, 'name': person.name, 'email': person.email,
            'system_role': person.role, 'active': person.active,
            'project_ids': sorted(by_user.get(person.id, set()))} for person in people]}

    @app.get('/team/projects/{project_id}/members')
    def members(project_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
        require_read(db, project_id, user)
        entries = db.execute(select(ProjectMember, User)
            .join(User, User.id == ProjectMember.user_id)
            .where(ProjectMember.project_id == project_id).order_by(User.name)).all()
        return {'can_manage': is_manager(db, project_id, user),
                'members': [row(member, person) for member, person in entries]}

    @app.post('/team/projects/{project_id}/members', status_code=201)
    def add_member(project_id: str, body: MembershipIn,
                   user: User = Depends(current_user), db: Session = Depends(get_db)):
        require_manager(db, project_id, user)
        members_with_lock(db, project_id)
        person = db.scalar(select(User).where(User.email == str(body.email), User.active.is_(True)))
        if person is None:
            raise HTTPException(404, 'Nincs ilyen aktív felhasználó')
        if db.get(ProjectMember, (project_id, person.id)) is not None:
            raise HTTPException(409, 'Ez a felhasználó már projekttag')
        member = ProjectMember(project_id=project_id, user_id=person.id, role=body.role)
        db.add(member)
        db.commit()
        return row(member, person)

    @app.patch('/team/projects/{project_id}/members/{user_id}')
    def update_member(project_id: str, user_id: str, body: RoleIn,
                      user: User = Depends(current_user), db: Session = Depends(get_db)):
        require_manager(db, project_id, user)
        members = members_with_lock(db, project_id)
        member = next((item for item in members if item.user_id == user_id), None)
        if member is None:
            raise HTTPException(404, 'A projekttag nem található')
        protect_last_owner(members, member, body.role)
        person = db.get(User, user_id)
        member.role = body.role
        db.commit()
        return row(member, person)

    @app.delete('/team/projects/{project_id}/members/{user_id}', status_code=204)
    def remove_member(project_id: str, user_id: str,
                      user: User = Depends(current_user), db: Session = Depends(get_db)):
        require_manager(db, project_id, user)
        members = members_with_lock(db, project_id)
        member = next((item for item in members if item.user_id == user_id), None)
        if member is None:
            raise HTTPException(404, 'A projekttag nem található')
        protect_last_owner(members, member, None)
        # Don't silently orphan existing assignments: require explicit reassignment first.
        from .models import Task
        assigned = db.scalar(select(Task.id).where(Task.project_id == project_id,
            Task.assigned_user_id == user_id, Task.deleted.is_(False)).limit(1))
        if assigned:
            raise HTTPException(409, 'Előbb rendeld át a felhasználó aktív feladatait')
        db.delete(member)
        db.commit()
        return None
