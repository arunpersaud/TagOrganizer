"""Tests for migration chain integrity and alignment with models.

This module verifies that the alembic migration chain produces schemas
identical to SQLModel.metadata.create_all(), ensuring the migrations
remain synchronized with the models and can be relied upon for
database initialization and upgrades.
"""

from sqlalchemy import inspect, text, create_engine as sa_create_engine
from sqlmodel import Session, SQLModel

from tagorganizer import db
from tagorganizer.models import Item, Tag, ItemTagLink
from tagorganizer.migrations import upgrade_db, downgrade_db

from conftest import alembic_head


class TestMigrationChainIntegrity:
    """Tests that verify the migration chain matches the models."""

    def normalize_schemas(self, inspector_alembic, inspector_sqlmodel):
        """Normalize schema representations for comparison.

        Returns two normalized dicts with keys: tables, columns, indexes, fks, pks.
        Normalization:
        - Alembic's alembic_version table is excluded (it's a migration artifact)
        - Column types are normalized to their string representation
        - Index names are ignored (they differ between alembic and create_all but
          are functionally equivalent if they cover the same columns)
        - Foreign key constraint names are ignored (both use naming convention
          and should be equivalent in function)
        - Primary key constraint names are ignored (functionally equivalent)
        """

        def normalize_inspector(inspector):
            # Exclude alembic_version table from comparison - it's a migration artifact
            tables = set(inspector.get_table_names()) - {"alembic_version"}
            normalized = {
                "tables": tables,
                "columns": {},
                "indexes": {},
                "fks": {},
                "pks": {},
            }

            for table in normalized["tables"]:
                # Normalize columns: extract name and type
                normalized["columns"][table] = {
                    col["name"]: str(col["type"])
                    for col in inspector.get_columns(table)
                }

                # Normalize indexes: group by columns only (ignore names)
                indexes = inspector.get_indexes(table)
                normalized["indexes"][table] = {
                    tuple(idx["column_names"]) for idx in indexes
                }

                # Normalize foreign keys: compare by columns and referred table
                fks = inspector.get_foreign_keys(table)
                normalized["fks"][table] = {
                    (
                        tuple(fk["constrained_columns"]),
                        fk["referred_table"],
                        tuple(fk["referred_columns"]),
                    )
                    for fk in fks
                }

                # Normalize primary keys: columns only (ignore name)
                pk = inspector.get_pk_constraint(table)
                if pk and pk["constrained_columns"]:
                    normalized["pks"][table] = tuple(pk["constrained_columns"])

            return normalized

        return normalize_inspector(inspector_alembic), normalize_inspector(
            inspector_sqlmodel
        )

    def test_migration_chain_matches_models(self, tmp_path, monkeypatch):
        """Test that alembic upgrade matches SQLModel.metadata.create_all().

        Runs the migration chain from base on one database and creates the schema
        via SQLModel.metadata.create_all() on another, then compares them for
        structural equivalence (same tables, columns, indexes, constraints).
        """
        # Prepare two fresh databases
        db_alembic_path = tmp_path / "alembic.db"
        db_sqlmodel_path = tmp_path / "sqlmodel.db"

        # Set up the alembic database
        db.set_engine(str(db_alembic_path))
        monkeypatch.setenv("TAGORGANIZER_DB_URL", f"sqlite:///{db_alembic_path}")

        # Create the database file so alembic has something to work with
        engine_alembic = sa_create_engine(f"sqlite:///{db_alembic_path}")
        engine_alembic.connect().close()
        db.engine = engine_alembic

        # Run migrations from base to head
        upgrade_db("head")

        # Set up the sqlmodel database
        engine_sqlmodel = sa_create_engine(f"sqlite:///{db_sqlmodel_path}")
        SQLModel.metadata.create_all(engine_sqlmodel)

        # Inspect both databases
        inspector_alembic = inspect(engine_alembic)
        inspector_sqlmodel = inspect(engine_sqlmodel)

        # Normalize and compare
        norm_alembic, norm_sqlmodel = self.normalize_schemas(
            inspector_alembic, inspector_sqlmodel
        )

        # Compare table names
        assert (
            norm_alembic["tables"] == norm_sqlmodel["tables"]
        ), f"Table mismatch. Alembic: {norm_alembic['tables']}, SQLModel: {norm_sqlmodel['tables']}"

        # Compare columns for each table
        for table in norm_sqlmodel["tables"]:
            # Ignore alembic_version table (migration-only)
            if table == "alembic_version":
                continue

            assert (
                table in norm_alembic["columns"]
            ), f"Table {table} missing in alembic schema"
            assert norm_alembic["columns"][table] == norm_sqlmodel["columns"][table], (
                f"Column mismatch in table {table}. "
                f"Alembic: {norm_alembic['columns'][table]}, "
                f"SQLModel: {norm_sqlmodel['columns'][table]}"
            )

            # Compare indexes
            assert norm_alembic["indexes"][table] == norm_sqlmodel["indexes"][table], (
                f"Index mismatch in table {table}. "
                f"Alembic: {norm_alembic['indexes'][table]}, "
                f"SQLModel: {norm_sqlmodel['indexes'][table]}"
            )

            # Compare foreign keys
            assert norm_alembic["fks"][table] == norm_sqlmodel["fks"][table], (
                f"Foreign key mismatch in table {table}. "
                f"Alembic: {norm_alembic['fks'][table]}, "
                f"SQLModel: {norm_sqlmodel['fks'][table]}"
            )

            # Compare primary keys
            assert norm_alembic["pks"][table] == norm_sqlmodel["pks"][table], (
                f"Primary key mismatch in table {table}. "
                f"Alembic: {norm_alembic['pks'][table]}, "
                f"SQLModel: {norm_sqlmodel['pks'][table]}"
            )

        print("✓ Alembic migration chain matches SQLModel.metadata.create_all()")

    def test_step_by_step_upgrade(self, tmp_path, monkeypatch):
        """Test that step-by-step upgrades work correctly.

        Verifies that upgrading from base -> c3c22277f560 -> 18ee44c097eb -> 9e42c23d5f4a
        works without errors and produces the expected schema at each step.
        """
        db_path = tmp_path / "step_test.db"

        db.set_engine(str(db_path))
        monkeypatch.setenv("TAGORGANIZER_DB_URL", f"sqlite:///{db_path}")

        engine = sa_create_engine(f"sqlite:///{db_path}")
        engine.connect().close()
        db.engine = engine

        # Start at base - just init alembic
        with engine.connect() as conn:
            conn.execute(
                text("""
                CREATE TABLE alembic_version (
                    version_num VARCHAR(32) PRIMARY KEY
                )
            """)
            )
            conn.commit()

        # Upgrade to c3c22277f560
        upgrade_db("c3c22277f560")

        inspector = inspect(engine)
        tables = inspector.get_table_names()
        assert "item" in tables
        assert "tag" in tables
        assert "itemtaglink" in tables

        # Verify the initial schema doesn't have longitude/latitude
        item_columns = {col["name"] for col in inspector.get_columns("item")}
        assert "longitude" not in item_columns
        assert "latitude" not in item_columns

        # Verify camera and date indexes exist
        item_indexes = {
            tuple(idx["column_names"]) for idx in inspector.get_indexes("item")
        }
        assert ("camera",) in item_indexes
        assert ("date",) in item_indexes

        # Upgrade to 18ee44c097eb (add geolocation)
        upgrade_db("18ee44c097eb")

        inspector = inspect(engine)
        item_columns = {col["name"] for col in inspector.get_columns("item")}
        assert "longitude" in item_columns
        assert "latitude" in item_columns

        # Verify geolocation indexes exist
        item_indexes = {
            tuple(idx["column_names"]) for idx in inspector.get_indexes("item")
        }
        assert ("longitude",) in item_indexes
        assert ("latitude",) in item_indexes

        # Upgrade to 9e42c23d5f4a (add uri and data_xxhash indexes)
        upgrade_db("9e42c23d5f4a")

        inspector = inspect(engine)
        item_indexes = {
            tuple(idx["column_names"]) for idx in inspector.get_indexes("item")
        }
        assert ("uri",) in item_indexes
        assert ("data_xxhash",) in item_indexes

        print("✓ Step-by-step upgrade from base to head works")

    def test_downgrade_to_base(self, tmp_path, monkeypatch):
        """Test that downgrading back to base works cleanly.

        Verifies that downgrading from head to base removes all tables and
        constraints without errors.
        """
        db_path = tmp_path / "downgrade_test.db"

        db.set_engine(str(db_path))
        monkeypatch.setenv("TAGORGANIZER_DB_URL", f"sqlite:///{db_path}")

        engine = sa_create_engine(f"sqlite:///{db_path}")
        engine.connect().close()
        db.engine = engine

        # Upgrade to head
        upgrade_db("head")

        # Verify tables exist
        inspector = inspect(engine)
        tables = set(inspector.get_table_names())
        assert "item" in tables
        assert "tag" in tables
        assert "itemtaglink" in tables

        # Downgrade to base (empty schema)
        downgrade_db("base")

        # Verify tables are gone (except alembic_version)
        inspector = inspect(engine)
        tables = set(inspector.get_table_names())
        assert "item" not in tables
        assert "tag" not in tables
        assert "itemtaglink" not in tables

        print("✓ Downgrade to base works cleanly")

    def test_alembic_version_tracking(self, tmp_path, monkeypatch):
        """Test that alembic version tracking is correct at each step."""
        db_path = tmp_path / "version_test.db"

        db.set_engine(str(db_path))
        monkeypatch.setenv("TAGORGANIZER_DB_URL", f"sqlite:///{db_path}")

        engine = sa_create_engine(f"sqlite:///{db_path}")
        engine.connect().close()
        db.engine = engine

        # Upgrade to c3c22277f560
        upgrade_db("c3c22277f560")

        with engine.connect() as conn:
            result = conn.execute(
                text("SELECT version_num FROM alembic_version")
            ).fetchone()
            assert result[0] == "c3c22277f560"

        # Upgrade to 18ee44c097eb
        upgrade_db("18ee44c097eb")

        with engine.connect() as conn:
            result = conn.execute(
                text("SELECT version_num FROM alembic_version")
            ).fetchone()
            assert result[0] == "18ee44c097eb"

        # Upgrade to head
        upgrade_db("head")

        with engine.connect() as conn:
            result = conn.execute(
                text("SELECT version_num FROM alembic_version")
            ).fetchone()
            assert result[0] == alembic_head()

        print("✓ Alembic version tracking is correct")

    def test_migration_chain_supports_data_operations(self, tmp_path, monkeypatch):
        """Test that the migrated schema actually supports data operations.

        Creates a database via migrations, inserts some test data, and verifies
        that the schema properly enforces constraints.
        """
        db_path = tmp_path / "data_test.db"

        db.set_engine(str(db_path))
        monkeypatch.setenv("TAGORGANIZER_DB_URL", f"sqlite:///{db_path}")

        engine = sa_create_engine(f"sqlite:///{db_path}")
        engine.connect().close()
        db.engine = engine

        # Upgrade to head
        upgrade_db("head")

        # Insert some test data
        with Session(engine) as session:
            # Create a tag
            tag = Tag(name="TestTag")
            session.add(tag)
            session.commit()
            session.refresh(tag)

            # Create an item
            item = Item(uri="/test/path.jpg")
            session.add(item)
            session.commit()
            session.refresh(item)

            # Link them
            link = ItemTagLink(item_id=item.id, tag_id=tag.id)
            session.add(link)
            session.commit()

            # Verify we can read back the data
            retrieved_item = session.get(Item, item.id)
            assert retrieved_item is not None
            assert retrieved_item.uri == "/test/path.jpg"

            retrieved_tag = session.get(Tag, tag.id)
            assert retrieved_tag is not None
            assert retrieved_tag.name == "TestTag"

            retrieved_link = session.get(ItemTagLink, (item.id, tag.id))
            assert retrieved_link is not None

        print("✓ Migrated schema supports data operations")
