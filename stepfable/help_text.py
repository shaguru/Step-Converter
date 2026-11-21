"""Every setting explained, in one place.

Used for the tooltips, for the explanation box under the settings panel and,
through scripts/build_docs.py, for the settings reference in docs/USER_GUIDE.md.
Each entry: (label, what it does, how to use it).
"""

STAGES = {
    "1  Cleanup": "Repairs the raw model before anything else: duplicate points, floating crumbs, "
                  "broken spots and small holes. Leave it on unless the model is already clean.",
    "2  Voxel remesh": "Rebuilds the whole model as one closed skin, the same idea as Blender's voxel remesh. "
                       "Use it when the model has overlapping pieces (ZBrush subtools), self-intersections "
                       "or lots of holes. Off by default because it softens fine detail.",
    "3  Smooth bumps": "Removes noise, voxel stair-steps and small sculpting bumps before the quads are made.",
    "4  Reduce": "Brings the face count down to roughly the number you ask for. This stage decides how many "
                 "quads you end up with, so it matters most for file size and speed.",
    "5  Quads": "Turns the triangles into quads. Smooth STEP export needs 100% quads.",
    "6  Relax + snap": "Evens out the quads so they are similar in size, and snaps every corner back onto the "
                       "surface after each step. This keeps the shape accurate.",
    "7  Measure": "Compares the result with the original and fills in the Runs table, so you can judge "
                  "settings by numbers instead of by eye.",
}

PARAMS = {
    # ---------------------------------------------------------------- 1 cleanup
    "cleanup": ("Enable cleanup",
                "Runs the repair steps of this section.",
                "Keep it on. Turn it off only to see the model exactly as it was loaded."),
    "weld_tolerance_pct": ("Weld distance %",
                           "Points closer together than this are merged into one. Measured as a percentage of "
                           "the model's overall size (its bounding-box diagonal).",
                           "0 merges only exact duplicates, which is safe. Try 0.01 to 0.05 if the model is "
                           "split into separate pieces along seams (common after UV splits or some exports). "
                           "Too high merges details that should stay apart."),
    "min_component_pct": ("Drop pieces smaller than %",
                          "Deletes separate floating pieces smaller than this percentage of the model's size.",
                          "1 removes stray crumbs. Raise it to remove bigger loose bits. Set 0 to keep every "
                          "piece, for example eyes or teeth that are separate objects."),
    "close_holes_max_edges": ("Close holes up to (edges)",
                              "Fills holes whose rim has at most this many edges.",
                              "100 fills small gaps. Raise it (for example 1000) to cap big openings such as a "
                              "cut-off neck, which CNC and 3D printing need. 0 leaves all holes open."),
    # ---------------------------------------------------------------- 2 voxel
    "voxel": ("Enable voxel remesh",
              "Rebuilds the model as one watertight surface on a 3D grid of tiny cubes.",
              "Turn it on for messy models: overlapping subtools, self-intersections, inside faces. "
              "Leave it off for clean sculpts, because it loses some fine detail."),
    "voxel_engine": ("Engine",
                     "Which program does the voxel remesh.",
                     "Built-in needs nothing extra. Blender (if installed) uses OpenVDB and is faster on huge "
                     "models."),
    "voxel_size_pct": ("Voxel size %",
                       "Size of each grid cube, as a percentage of the model's size.",
                       "Smaller keeps more detail but is slower and uses more memory. 0.5 is a good start. "
                       "0.2 for detailed faces and hands. 1.0 for a quick rough pass."),
    # ---------------------------------------------------------------- 3 smoothing
    "smooth_method": ("Method",
                      "How bumps are smoothed out.",
                      "Taubin: smooths without shrinking the model; the best general choice. "
                      "Feature-preserving: keeps sharp creases and edges; use it for hard-surface or "
                      "mechanical parts. HC Laplacian: very gentle. Off: keep every sculpted detail."),
    "smooth_iterations": ("Iterations",
                          "How many smoothing passes to run.",
                          "More passes give a smoother surface but lose more detail. 5 to 10 is light, "
                          "30 to 60 is strong (clears voxel stair-steps), and above 100 melts details."),
    "smooth_feature_angle": ("Crease angle °",
                             "Feature-preserving smoothing only: where the surface bends more sharply than this "
                             "angle, it counts as a crease and is kept sharp.",
                             "Lower (20 to 30) protects more edges. Higher (60+) smooths more of them away."),
    # ---------------------------------------------------------------- 4 reduce
    "reduce_method": ("Method",
                      "How the face count is reduced to the target.",
                      "Isotropic remesh: even, regular triangles; these pair into the cleanest quads, so use "
                      "it for STEP/CNC. Quadric decimation: keeps the most detail per face, but faces are "
                      "uneven. Off: keeps every face; the result can be huge and STEP export very slow."),
    "target_faces": ("Target faces",
                     "Roughly how many faces (quads) you want in the result.",
                     "This is the main size control. For CNC/STEP, 2,000 to 10,000 usually looks smooth "
                     "and accurate (smooth STEP surfaces fill in the curves). For STL printing, 50,000 to "
                     "300,000 keeps fine detail. Check the Mean dev column: if it barely improves when you "
                     "double this number, the lower number is enough."),
    "isotropic_iterations": ("Isotropic iterations",
                             "Isotropic remesh only: how many passes are used to even out the triangles.",
                             "6 is good. More gives slightly more even faces and takes longer."),
    "preserve_boundary": ("Keep open borders",
                          "Keeps the edges of open holes exactly where they are.",
                          "Keep it on for open models (a mask, a relief panel) so their outline doesn't shrink. "
                          "It has no effect on closed models."),
    # ---------------------------------------------------------------- 5 quads
    "quad_method": ("Method",
                    "How triangles become quads.",
                    "Pair + split (built-in): always 100% quads, fast, no extra software; the default. "
                    "Pair: quad-dominant with some triangles left, fewer faces. Blender QuadriFlow / Instant "
                    "Meshes: flowing edge loops with fewer poles, but they need Blender or Instant Meshes "
                    "installed. Keep triangles: no quads (fine for STL only)."),
    "quad_feature_angle": ("Don't pair across °",
                           "Two triangles are never merged into one quad across a fold sharper than this angle.",
                           "Lower (20 to 30) keeps hard edges as quad borders, which is good for mechanical parts. "
                           "Higher allows more pairs on organic shapes."),
    "quadriflow_preserve_sharp": ("QuadriFlow: keep sharp",
                                  "Blender QuadriFlow only: tries to keep edge loops along sharp edges.",
                                  "Turn it on for hard-surface models."),
    "quadriflow_symmetry": ("QuadriFlow: use symmetry",
                            "Blender QuadriFlow only: makes the quad layout mirror-symmetric (X axis).",
                            "Turn it on for symmetric characters whose middle is on X = 0."),
    "instant_crease_angle": ("Instant Meshes crease °",
                             "Instant Meshes only: edges sharper than this angle are kept as edge loops.",
                             "0 is off. Try 30 to 45 for hard-surface parts."),
    "instant_smooth_iters": ("Instant Meshes smoothing",
                             "Instant Meshes only: how many smoothing passes its direction field gets.",
                             "2 is the default. Higher gives smoother, straighter loops."),
    # ---------------------------------------------------------------- 6 relax
    "relax_iterations": ("Relax iterations",
                         "How many times the quads are evened out. After each pass every point is snapped "
                         "back onto the surface.",
                         "3 to 8 is typical. 0 skips relaxing (the points are still snapped once). More makes "
                         "squarer, more even quads."),
    "relax_strength": ("Relax strength",
                       "How far each point moves per relax pass (0 = not at all, 1 = fully).",
                       "0.5 is balanced. Lower is gentler on fine detail."),
    "project_to": ("Snap to",
                   "Which surface the quads are snapped onto.",
                   "Smoothed surface keeps the bumps you removed in step 3 away. Original sculpt hugs the raw "
                   "model, bumps included, for the most faithful copy. Don't snap leaves points where the "
                   "quad step put them (fastest, least accurate)."),
    # ---------------------------------------------------------------- 7 measure
    "measure": ("Measure accuracy",
                "After each run, measures how far the result is from the original.",
                "Keep it on: the Runs table and the deviation colours need it."),
    "measure_samples": ("Samples",
                        "How many surface points are compared for the accuracy numbers.",
                        "60,000 is precise enough. Raise it for very large, detailed models, or lower it to "
                        "save a second or two."),
}

EXPORT = {
    "formats": ("Formats",
                "Which file types are written when you press Export. Each one goes into the folder you choose.",
                "STEP: CAD/CAM and CNC (exact surfaces). STL: 3D printing and most CAM. OBJ and FBX: other "
                "3D apps, quads kept. GLB/glTF: web and game engines. PLY: scanning and point tools."),
    "step_mode": ("STEP surfaces",
                  "How the faces are written into the STEP file.",
                  "Smooth surfaces: every quad becomes a curved patch; neighbouring patches meet exactly; "
                  "best for CNC, needs 100% quads. Flat faces, quads kept: flat facets like the mesh. "
                  "Flat triangles: the most compatible with old software, but the biggest files."),
    "step_unit": ("STEP units",
                  "The unit written into the STEP file. Coordinates are not converted.",
                  "Pick the unit your model was made in. To convert, use Scale on export as well (for "
                  "example cm to mm: unit MM and scale 10)."),
    "step_sharp_angle": ("Smooth: crease above °",
                         "Smooth STEP only: where neighbouring quads meet at a sharper angle than this, the "
                         "edge stays a crisp crease instead of being rounded.",
                         "50 suits organic models. Use 20 to 30 to keep more hard edges on mechanical parts."),
    "scale": ("Scale on export",
              "Multiplies every coordinate when exporting.",
              "1 keeps the size. 10 turns cm into mm, 25.4 turns inches into mm, 0.1 turns mm into cm."),
}

RUNS_COLUMNS = {
    "Faces": "Number of faces in the result.",
    "Quads %": "Share of faces that are quads. Smooth STEP needs 100.",
    "Irregular %": "Points that don't have exactly 4 edges (poles). Lower means cleaner edge flow. "
                   "Built-in methods give about 15; QuadriFlow and Instant Meshes usually give under 10.",
    "Angle dev °": "Average distance of quad corners from a perfect 90°. Under 15 is good.",
    "Mean dev %": "Average distance between the result and the original, as a % of model size. "
                  "The main accuracy number. For CNC, under 0.02% is excellent.",
    "95% dev %": "95% of the surface is closer to the original than this.",
    "Max dev %": "The single worst spot. Often a thin tip or a deep crease.",
    "Mean dev": "The average distance in model units (for example mm).",
    "Time s": "How long the run took.",
}


def tooltip(entry) -> str:
    label, what, how = entry
    return f"<b>{label}</b><br>{what}<br><br>{how}"


def plain(entry) -> str:
    label, what, how = entry
    return f"{what} {how}"
