from sqlmodel import SQLModel, create_engine, select, Session, func

from .models import Tag, Item
from .config import get_or_create_db_path

database_url = get_or_create_db_path()
engine = create_engine(database_url)


def create_db():
    SQLModel.metadata.create_all(engine)


def get_tag(name):
    with Session(engine) as session:
        return session.exec(select(Tag).where(Tag.name == name)).first()


def get_tag_by_id(id):
    with Session(engine) as session:
        return session.exec(select(Tag).where(Tag.id == id)).first()


def add_tag(name):
    with Session(engine) as session:
        new_tag = Tag(name=name)
        session.add(new_tag)
        session.commit()
        return new_tag.id


def get_all_tags():
    with Session(engine) as session:
        results = session.exec(select(Tag))
        return results.all()


def set_parent_tag(child, parent):
    if child is None:
        print("No child given")
    if parent is None:
        print("No parent given")

    with Session(engine) as session:
        child.parent_id = parent.id
        session.add(child)
        session.commit()


def add_images(files):
    with Session(engine) as session:
        for f in files:
            tmp = Item(uri=str(f))
            session.add(tmp)
        session.commit()


def get_images(page=0):
    with Session(engine) as session:
        results = session.exec(select(Item).offset(25 * page).limit(25))
        return results.all()


def get_number_of_items():
    with Session(engine) as session:
        statement = select(func.count(Item.id))
        return session.exec(statement).one()
