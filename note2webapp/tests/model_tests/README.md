# Model Tests
This directory contains all model-level unit tests for the note2webapp app.

Each file focuses on a specific model:
- 'model_test_version_timestamp.py'-> Verifies that new `ModelVersion` instances appear immediately, and that timestamps (`created_at`) and notes (`log`) fields are properly set.
- 'model_test_version_softdelete.py'-> Ensures soft-deleted versions correctly set `is_deleted` and `deleted_at`, and verifies deleted versions are excluded from active querysets.
- 'test_model_upload.py'-> Tests creation of `ModelUpload`, string representation, version relationships, and cascade delete behavior.


Run **all model tests**:
```bash
python manage.py test note2webapp.tests.model_tests
