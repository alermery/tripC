from backend.app.api import rag_admin


def test_rag_task_registry_shape():
    assert isinstance(rag_admin._tasks, dict)
    assert rag_admin._ALLOWED == {".txt", ".csv", ".xlsx"}
