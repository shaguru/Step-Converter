"""Order of the remesh settings in the UI (no Qt imports, so docs can use it)."""

PARAM_GROUPS = [
    ('1  Cleanup', ['cleanup', 'weld_tolerance_pct', 'min_component_pct', 'close_holes_max_edges']),
    ('2  Voxel remesh', ['voxel', 'voxel_engine', 'voxel_size_pct']),
    ('3  Smooth bumps', ['smooth_method', 'smooth_iterations', 'smooth_feature_angle']),
    ('4  Reduce', ['reduce_method', 'target_faces', 'isotropic_iterations', 'preserve_boundary']),
    ('5  Quads', ['quad_method', 'quad_feature_angle', 'quadriflow_preserve_sharp', 'quadriflow_symmetry', 'instant_crease_angle', 'instant_smooth_iters']),
    ('6  Relax + snap', ['relax_iterations', 'relax_strength', 'project_to']),
    ('6b Flat faces (hard surface)', ['flat_faces', 'flat_tolerance_pct', 'flat_max_move_pct', 'flat_min_area_pct', 'flat_refine_trials']),
    ('7  Measure', ['measure', 'measure_samples']),
]
