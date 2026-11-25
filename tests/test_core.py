"""Run with:  env\\Scripts\\python -m pytest tests"""
import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from stepfable import io_formats as io                       # noqa: E402
from stepfable.mesh import PolyMesh                           # noqa: E402
from stepfable.remesh import RemeshParams, run_pipeline       # noqa: E402


def cube():
    v = np.array([[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0], [0, 0, 1], [1, 0, 1], [1, 1, 1], [0, 1, 1.3]], float)
    q = [[0, 3, 2, 1], [4, 5, 6, 7], [0, 1, 5, 4], [1, 2, 6, 5], [2, 3, 7, 6], [3, 0, 4, 7]]
    return PolyMesh.from_quads(v, q, "cube")


def bumpy_sphere(sub=5):
    import trimesh
    s = trimesh.creation.icosphere(sub)
    v = s.vertices * (1 + 0.01 * np.sin(20 * s.vertices[:, 0]) * np.sin(20 * s.vertices[:, 1]))[:, None]
    return PolyMesh.from_triangles(v, s.faces, "sphere")


def step_solid(path):
    from OCP.BRepCheck import BRepCheck_Analyzer
    from OCP.BRepGProp import BRepGProp
    from OCP.GProp import GProp_GProps
    from OCP.STEPControl import STEPControl_Reader
    r = STEPControl_Reader()
    r.ReadFile(path)
    r.TransferRoots()
    s = r.OneShape()
    p = GProp_GProps()
    BRepGProp.VolumeProperties_s(s, p)
    return BRepCheck_Analyzer(s).IsValid(), p.Mass()


@pytest.mark.parametrize("ext", io.EXPORT_EXTS)
def test_roundtrip(tmp_path, ext):
    m = cube()
    path = str(tmp_path / f"c{ext}")
    io.save(m, path)
    back = io.load(path)
    lo, hi = back.bounds
    assert np.allclose(lo, [0, 0, 0], atol=1e-5) and np.allclose(hi, [1, 1, 1.3], atol=1e-5)
    if ext in (".obj", ".fbx"):
        assert back.stats()["quads"] == 6


def test_step_flat_solid(tmp_path):
    path = str(tmp_path / "c.step")
    io.save(cube(), path)
    ok, vol = step_solid(path)
    assert ok and abs(vol - 1.075) < 1e-6          # bilinear twisted face is exact


def test_pipeline_and_smooth_step(tmp_path):
    m = bumpy_sphere()
    r, rep = run_pipeline(m, RemeshParams(target_faces=1500, reduce_method="isotropic"))
    assert rep["quad_pct"] == 100.0
    assert rep["dev_mean_pct"] < 0.5
    path = str(tmp_path / "s.step")
    io.save(r, path, step_mode="smooth")
    ok, vol = step_solid(path)
    assert ok and abs(vol - 4 / 3 * np.pi) / (4 / 3 * np.pi) < 0.02


def test_flat_faces_merge_into_one_step_face_each(tmp_path):
    import trimesh
    box = trimesh.creation.box((2.0, 1.0, 0.5))
    box = box.subdivide().subdivide().subdivide()
    rng = np.random.default_rng(0)
    v = box.vertices + rng.normal(0, 2e-5, box.vertices.shape)     # slightly noisy, like a decimated scan
    m = PolyMesh.from_triangles(v, box.faces, "box")
    p = RemeshParams(smooth_method="none", reduce_method="quadric", target_faces=600, quad_method="none",
                     relax_iterations=0, project_to="none", flat_faces=True)
    r, rep = run_pipeline(m, p)
    assert rep["flat_planes"] == 6
    path = str(tmp_path / "b.step")
    info = io.save(r, path)
    from stepfable.hard_surface import merged_faces
    assert len(merged_faces(r)) == 6
    ok, vol = step_solid(path)
    assert ok and abs(vol - 1.0) < 1e-3


def test_every_setting_is_documented():
    from dataclasses import fields
    from stepfable import help_text
    from stepfable.app_spec import PARAM_GROUPS
    from stepfable.remesh import RemeshParams
    names = {f.name for f in fields(RemeshParams)}
    assert names == set(help_text.PARAMS)
    assert names == {n for _t, ns in PARAM_GROUPS for n in ns}
    assert all(t in help_text.STAGES for t, _ in PARAM_GROUPS)
