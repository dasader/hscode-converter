# backend/tests/test_batch_routes.py
import os
import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock
from openpyxl import Workbook

os.environ.setdefault("OPENAI_API_KEY", "sk-test-dummy-key")
os.environ.setdefault("ADMIN_API_KEY", "test-admin-key")


@pytest.fixture
def excel_file(tmp_path):
    wb = Workbook()
    ws = wb.active
    ws.append(["과제명", "기술설명"])
    ws.append(["과제A", "리튬이온 배터리 양극재 제조를 위한 니켈 코발트 망간 합성 기술 설명"])
    path = str(tmp_path / "test.xlsx")
    wb.save(path)
    return path


@pytest.fixture
def client():
    from app.main import app
    with TestClient(app) as c:
        yield c


def test_template_download(client):
    response = client.get("/api/v1/batch/template")
    assert response.status_code == 200
    assert "spreadsheet" in response.headers["content-type"]


def test_upload_no_file(client):
    response = client.post("/api/v1/batch/upload")
    assert response.status_code == 422


def test_jobs_list(client):
    response = client.get("/api/v1/batch/jobs")
    assert response.status_code == 200
    assert "jobs" in response.json()
