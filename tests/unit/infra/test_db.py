import pathlib

import sqlalchemy

import operant.infra.db.engine as engine
import operant.infra.db.migrate as migrate
import operant.infra.db.models as models
import operant.infra.repositories.runs as rrruns


def test_migrations_reach_head_and_match_the_models(
    tmp_path: pathlib.Path,
) -> None:
    database = engine.Database.open(tmp_path / "state" / "op.sqlite3")
    assert migrate.current_revision(database) is None
    migrate.upgrade(database)
    assert migrate.current_revision(database) == "0005"
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


def test_edge_reviews_are_kept_per_graph_version(
    tmp_path: pathlib.Path,
) -> None:
    database = engine.Database.open(tmp_path / "state" / "op.sqlite3")
    migrate.upgrade(database)
    reviews = rrruns.SqlRunRepository(database).edge_records
    key = ("e1", "link", "reports")
    assert not reviews.is_approved("app", 1, key)
    reviews.approve("app", 1, [key], by="a person")
    reviews.approve("app", 1, [key], by="a person")
    assert reviews.is_approved("app", 1, key)
    assert not reviews.is_approved("app", 2, key)


def test_an_edge_that_never_passed_and_failed_twice_is_failing(
    tmp_path: pathlib.Path,
) -> None:
    database = engine.Database.open(tmp_path / "state" / "op.sqlite3")
    migrate.upgrade(database)
    records = rrruns.SqlRunRepository(database).edge_records
    records.record_outcome("app", 1, "broken", passed=False)
    assert records.failing("app") == set()
    records.record_outcome("app", 1, "broken", passed=False)
    records.record_outcome("app", 1, "flaky", passed=False)
    records.record_outcome("app", 1, "flaky", passed=False)
    records.record_outcome("app", 1, "flaky", passed=True)
    assert records.failing("app") == {"broken"}


def test_closed_samples_stop_counting(tmp_path: pathlib.Path) -> None:
    database = engine.Database.open(tmp_path / "state" / "op.sqlite3")
    migrate.upgrade(database)
    runs = rrruns.SqlRunRepository(database)
    runs.record_stability("cap", "r1", succeeded=True)
    runs.close_samples("cap")
    runs.record_stability("cap", "r2", succeeded=False)
    track = runs.stability("cap")
    assert (track.runs, track.successes) == (1, 0)
