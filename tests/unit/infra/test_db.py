import pathlib

import sqlalchemy

import operant.infra.db.engine as engine
import operant.infra.db.migrate as migrate
import operant.infra.db.models as models


def test_migrations_reach_head_and_match_the_models(
    tmp_path: pathlib.Path,
) -> None:
    database = engine.Database.open(tmp_path / "state" / "op.sqlite3")
    assert migrate.current_revision(database) is None
    migrate.upgrade(database)
    assert migrate.current_revision(database) == "0003"
    inspector = sqlalchemy.inspect(database.engine)
    assert set(models.Base.metadata.tables) <= set(inspector.get_table_names())
    database.close()


def test_memory_migration_drops_verifier_lessons_and_keeps_notes(
    tmp_path: pathlib.Path,
) -> None:
    database = engine.Database.open(tmp_path / "op.sqlite3")
    migrate.upgrade(database, "0002")
    with database.engine.begin() as connection:
        for source in ("verifier", "human"):
            connection.execute(
                sqlalchemy.text(
                    "INSERT INTO lessons (vendor_id, goal_key, lesson, source,"
                    " reinforcements, last_used_at) VALUES"
                    " ('app', 'goal', :text, :source, 1, 'now')"
                ),
                {"text": f"from {source}", "source": source},
            )
    migrate.upgrade(database)
    with database.engine.begin() as connection:
        rows = connection.execute(
            sqlalchemy.text("SELECT source, graph_version FROM lessons")
        ).all()
    assert [tuple(row) for row in rows] == [("human", 0)]
    database.close()


def test_in_memory_database_shares_state_across_sessions() -> None:
    database = engine.Database.open(None)
    database.create_all()
    with database.session() as session:
        session.add(
            models.StabilityRecordRow(capability_id="cap", runs=1, successes=1)
        )
    with database.session() as session:
        row = session.get(models.StabilityRecordRow, "cap")
        assert row is not None and row.runs == 1
    database.close()
