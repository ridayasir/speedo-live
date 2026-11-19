"""Every document the app wrote during the test run must be accepted by the real Firestore client encoder."""
from google.cloud.firestore_v1 import _helpers

from .conftest import FIRESTORE


def test_all_documents_encode_for_firestore(client, admin_h):
    client.get("/api/admin/overview", headers=admin_h)
    count = 0
    for coll, docs in FIRESTORE.data.items():
        for doc_id, data in docs.items():
            _helpers.encode_dict(data)  # raises on any value Firestore cannot store
            count += 1
    assert count > 50
