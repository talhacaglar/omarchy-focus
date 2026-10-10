from __future__ import annotations

import json
import ssl
import threading
import urllib.error
import urllib.request
import uuid

import pytest

from omarchy_focus.database import Database
from omarchy_focus.mobile_sync import exchange, make_server, prepare_pairing
from omarchy_focus.services.tasks import TaskService


@pytest.fixture
def db(tmp_path):
    result = Database(tmp_path / "focus.db")
    result.initialize()
    return result


def operation(uid=None, base=0, kind="upsert", **fields):
    return {"id": uuid.uuid4().hex, "uid": uid or uuid.uuid4().hex,
            "base": base, "kind": kind, "fields": fields}


def send(db, *ops):
    return exchange(db, {"protocol": 1, "dataset": db.fetchone("SELECT id FROM sync_identity")[0],
                         "operations": list(ops)})


def test_mobile_add_retry_and_desktop_completion(db):
    op = operation(title="Telefondan görev", priority="high")
    first = send(db, op)
    assert first["accepted"] == [op["id"]]
    assert first["tasks"][0]["title"] == "Telefondan görev"
    assert send(db, op)["tasks"] == first["tasks"]
    service = TaskService(db)
    assert len(service.list_tasks()) == 1
    service.complete_task(service.list_tasks()[0].id, notifications_enabled=False)
    assert send(db)["tasks"][0]["status"] == "done"


def test_stale_offline_edit_does_not_overwrite_desktop(db):
    service = TaskService(db)
    task = service.add_task("Original", tags="keep", estimated_minutes=25)
    record = send(db)["tasks"][0]
    service.update_task(task.id, title="Desktop edit")
    op = operation(record["uid"], record["version"], title="Phone edit")
    response = send(db, op)
    assert response["conflicts"] == [record["uid"]]
    assert service.get_task(task.id).title == "Desktop edit"
    resolved = operation(record["uid"], response["tasks"][0]["version"], title="Phone edit")
    assert send(db, resolved)["conflicts"] == []
    assert service.get_task(task.id).title == "Phone edit"
    assert service.get_task(task.id).tags == ("keep",)
    assert service.get_task(task.id).estimated_minutes == 25


def test_deleted_desktop_task_cannot_be_resurrected(db):
    service = TaskService(db)
    task = service.add_task("Remove me")
    record = send(db)["tasks"][0]
    service.delete_task(task.id)
    op = operation(record["uid"], record["version"], title="Offline edit")
    assert send(db, op)["conflicts"] == [record["uid"]]
    assert send(db)["tasks"][0]["deleted"] == 1
    assert service.list_tasks() == []
    # Even an explicit matching tombstone version cannot resurrect the old UID.
    op = operation(record["uid"], send(db)["tasks"][0]["version"], title="Resurrect")
    assert send(db, op)["conflicts"]


def test_mobile_delete_is_idempotent(db):
    create = operation(title="Temporary")
    record = send(db, create)["tasks"][0]
    delete = operation(record["uid"], record["version"], kind="delete")
    response = send(db, delete)
    assert response["tasks"][0]["deleted"] == 1
    assert send(db, delete) == response
    assert not TaskService(db).list_tasks()


def test_lost_create_then_offline_delete(db):
    create = operation(title="Sent without receiving response")
    record = send(db, create)["tasks"][0]
    delete = operation(record["uid"], 0, kind="delete")
    assert send(db, delete)["conflicts"]
    delete = operation(record["uid"], record["version"], kind="delete")
    assert send(db, delete)["tasks"][0]["deleted"] == 1


@pytest.mark.parametrize("fields", [{"title": " "}, {"title": "x", "priority": "urgent"},
                                    {"title": "x", "status": "invalid"}, {"title": "x", "id": 123},
                                    {"title": "x", "description": 42}])
def test_bad_payloads_do_not_write(db, fields):
    with pytest.raises(ValueError):
        send(db, operation(**fields))
    assert TaskService(db).list_tasks() == []


def test_atomic_batch_rollback_and_identity_check(db):
    op = operation(title="Must roll back")
    with pytest.raises(ValueError):
        send(db, op, operation(description="Missing title"))
    assert send(db)["tasks"] == []
    with pytest.raises(ValueError):
        exchange(db, {"protocol": 1, "dataset": "other", "operations": [op]})
    assert send(db)["tasks"] == []


def test_receipt_reuse_with_different_payload_rejected(db):
    op = operation(title="Original")
    send(db, op)
    op["fields"]["title"] = "Changed payload"
    with pytest.raises(ValueError, match="reused"):
        send(db, op)
    assert TaskService(db).list_tasks()[0].title == "Original"


def test_v1_migration_preserves_ids_and_fields(tmp_path):
    db = Database(tmp_path / "old.db")
    db.initialize()
    task = TaskService(db).add_task("Keep this", tags="old", estimated_minutes=15)
    with db.connection() as conn:
        for name in ("sync_task_insert", "sync_task_update", "sync_task_delete"):
            conn.execute(f"DROP TRIGGER {name}")
        for name in ("sync_tasks", "sync_receipts", "sync_identity"):
            conn.execute(f"DROP TABLE {name}")
        conn.execute("PRAGMA user_version = 1")
    db.initialize()
    after = TaskService(db).get_task(task.id)
    assert after == task
    first = send(db)
    db.initialize()
    assert send(db) == first


def test_tls_endpoint_requires_pairing_and_rejects_bad_requests(db, tmp_path):
    directory = tmp_path / "credentials"
    pair_path = prepare_pairing(db, directory, "127.0.0.1", 0)
    assert pair_path.stat().st_mode & 0o777 == 0o600
    server = make_server(db, directory, "127.0.0.1", 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    ctx = ssl.create_default_context(cafile=str(directory / "cert.pem"))
    ctx.check_hostname = False  # Test trusts only this generated certificate.
    url = f"https://127.0.0.1:{server.server_port}/v1/exchange"
    pairing = json.loads(pair_path.read_text())
    body = json.dumps({"protocol": 1, "dataset": pairing["dataset"], "operations": []}).encode()
    try:
        with pytest.raises(urllib.error.HTTPError) as error:
            urllib.request.urlopen(urllib.request.Request(url, data=body), context=ctx)
        assert error.value.code == 401
        request = urllib.request.Request(url, data=body, headers={"Authorization": "Bearer " + pairing["token"]})
        with urllib.request.urlopen(request, context=ctx) as response:
            assert json.load(response)["tasks"] == []
        request = urllib.request.Request(url, data=b"{", headers={"Authorization": "Bearer " + pairing["token"]})
        with pytest.raises(urllib.error.HTTPError) as error:
            urllib.request.urlopen(request, context=ctx)
        assert error.value.code == 400
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
