from fastapi.testclient import TestClient

from email_article_analyzer.main import create_app


def test_health_endpoint_reports_ok(tmp_path):
    app = create_app(database_path=str(tmp_path / "app.db"))
    client = TestClient(app)

    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
