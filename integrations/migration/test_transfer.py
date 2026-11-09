import copy
import json
from pathlib import Path
import tempfile
import unittest
import uuid

from context_transfer import VERSION, FULL_VERSION, digest, load_package, plan


def package():
    return dict(version=VERSION, scope="sample", source_store="synthetic-separate-store",
                source_revision="synthetic-v1", snapshot_id="sample-1",
                destination=dict(origin="http://localhost:3401", admin_user_id=str(uuid.uuid4())),
                record_counts={"object": 1}, files=[],
                groups=[dict(id="parent", depends_on=[], records=[dict(type="object", object={"id": str(uuid.uuid4())})])])


class PackageTests(unittest.TestCase):
    def test_full_package_requires_matching_complete_snapshot_evidence(self):
        p = package()
        p.update(version=FULL_VERSION, scope="full", source_evidence=dict(
            snapshot=dict(kind="quiesced_source", backup_sha256="b"*64, writer_fence="Verified synthetic fence"),
            consistency="fenced_full_snapshot_two_equal_observations", selected_counts={"objects":1},
            opening_catalog={"objects":{"row_count":1}}, closing_catalog={"objects":{"row_count":1}},
            observed_counts=[{"objects":1}, {"objects":1}]))
        self.assertEqual(len(plan(p)[1]), 1)
        for mutate in (lambda q: q["source_evidence"]["snapshot"].update(backup_sha256="unknown"),
                       lambda q: q["source_evidence"].update(selected_counts={"objects":2}),
                       lambda q: q["source_evidence"].update(observed_counts=[{"objects":1}, {"objects":2}]),
                       lambda q: q["source_evidence"].update(consistency="two_equal_observations_not_an_atomic_snapshot")):
            changed = copy.deepcopy(p)
            mutate(changed)
            with self.assertRaises(ValueError):
                plan(changed)

    def test_dependency_order_and_fail_closed(self):
        p = package()
        child = dict(id="child", depends_on=["parent"], records=[dict(type="history", id=str(uuid.uuid4()))])
        p["groups"].insert(0, child)
        p["record_counts"]["history"] = 1
        self.assertEqual([g["id"] for g in plan(p)[1]], ["parent", "child"])
        for mutation in (lambda q: q["groups"][1].update(depends_on=["child"]),
                         lambda q: q["groups"][0].update(depends_on=["absent"]),
                         lambda q: q.update(record_counts={"object": 1}),
                         lambda q: q.update(scope="full"),
                         lambda q: q["groups"][0].update(records=[dict(type="unknown", id=str(uuid.uuid4()))]),
                         lambda q: q["groups"][0].update(records=q["groups"][1]["records"]),
                         lambda q: q["groups"][0].update(records=[dict(type="history", id=str(uuid.uuid4())) for _ in range(51)])):
            changed = copy.deepcopy(p)
            mutation(changed)
            with self.assertRaises(ValueError):
                plan(changed)

    def test_private_file_bytes_dispositions_and_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            p = package()
            payload = b"original PDF fixture bytes, not extracted text"
            (root / "original.pdf").write_bytes(payload)
            (root / "original.pdf").chmod(0o600)
            p["files"] = [dict(reference="opaque:source.pdf", status="packaged", reason="Explicit original",
                               path="original.pdf", sha256=digest(payload), size_bytes=len(payload)),
                          dict(reference="relative/missing.pdf", status="unresolved", reason="Base unknown"),
                          dict(reference="generated.mp4", status="excluded", reason="Approved generated clip exclusion")]
            manifest = root / "package.json"
            manifest.write_text(json.dumps(p))
            manifest.chmod(0o600)
            self.assertEqual(load_package(root), p)
            (root / "original.pdf").write_bytes(payload + b"corruption")
            with self.assertRaisesRegex(ValueError, "checksum"):
                load_package(root)
            (root / "original.pdf").write_bytes(payload)
            (root / "alias").symlink_to(root / "original.pdf")
            for path in ("../outside", "/absolute", "alias"):
                p["files"][0]["path"] = path
                manifest.write_text(json.dumps(p))
                with self.assertRaises(ValueError):
                    load_package(root)

    def test_utf8_artifact_hashes(self):
        p = package()
        p["groups"][0]["records"] = [dict(type="artifact", id=str(uuid.uuid4()),
            artifact={"body": "Exact α\r\n"}, sha256=digest("Exact α\r\n".encode()))]
        p["record_counts"] = {"artifact": 1}
        plan(p)
        p["groups"][0]["records"][0]["artifact"]["body"] = "Exact α\n"
        with self.assertRaisesRegex(ValueError, "checksum"):
            plan(p)


if __name__ == "__main__":
    unittest.main()
