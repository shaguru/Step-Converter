# Step Converter user guide

Step Converter does two jobs:

1. **Converts** 3D files between STEP, STL, OBJ, FBX, glTF, GLB and PLY.
2. **Remeshes** dense sculpts (ZBrush, Blender sculpt, scans) into clean, accurate **quads**, so they export as smooth **STEP** solids for CAD/CNC or as tidy **STL** for 3D printing.

You can always tune by numbers instead of guessing: every remesh is measured against the original, and the results go into the **Runs** table so you can compare settings side by side.

In the app, point at any setting to see what it does in the box under the settings panel, or press **F1** to open this guide.

---

## 1. Your first conversion in two minutes (monkey example)

The download includes an example sculpt: `samples\monkeyGeo.fbx` (about 230,000 faces, half triangles and half quads).

1. Start Step Converter.
2. Click **Open example** in the toolbar. (It is the file `samples\monkeyGeo.fbx`; you can also open it with **Open…** or drag it onto the window.) It appears in the **Files** list and on the left side of the 3D view (*Original*).
3. In **Preset** (top right) choose **01 Sculpt to CNC - smooth STEP**.
4. Press **▶ Remesh** (or **F5**). After a few seconds the right side of the view shows the *Result*, and a row is added to the **Runs** table. On a typical PC you get about **4,250 quads, 100% quads**, with a mean deviation of about **0.03%** of the model size.
5. Turn on **Smooth STEP preview** in the toolbar. This shows the exact curved surfaces the STEP file will contain. **Wireframe** (W) draws the quad edges on top.
6. Turn on **Deviation colours** (H) to see where the result differs from the sculpt. Blue is close, red is furthest away.
7. In **Export** (bottom right) tick **STEP** and **STL**, then press **Export…** and pick a folder. You get `monkeyGeo_quads.step` (about 6.5 MB, one closed solid) and `monkeyGeo_quads.stl`.
8. Open the STEP file in your CAD/CAM program (Fusion, SolidWorks, Rhino, FreeCAD and others). It arrives as one solid body, not a pile of loose surfaces.

Want more detail? Change **Target faces** to 10,000 and press Remesh again. Both runs now sit in the Runs table; click a row to view it.

---

## 2. The screen

| Area | What it is for |
|---|---|
| **Toolbar** (top) | Open, Remesh, Compare presets, Cancel, Export, Batch, view switches, Settings, Help |
| **Files** (left) | Everything you've opened or dropped. Click a file to load it. Select several and press *Remove selected* to clear them. |
| **3D view** (centre) | *Original* on the left, *Result* on the right. The two cameras move together. Left-drag rotates, right-drag or the wheel zooms, middle-drag pans. **R** resets the view. |
| **Runs** (below the view) | One row per remesh, with its accuracy numbers. Click a row to show that result. **Use these settings** copies that run's settings back into the panel. **Clear** empties the table. |
| **Settings panel** (right) | The preset menu, the seven numbered remesh stages, and the export options. |
| **Explanation box** (under the settings) | Shows what the setting under your mouse does and how to set it. |

### Toolbar

| Button | Key | What it does |
|---|---|---|
| **Open…** | Ctrl+O | Add files to the Files list. You can also drag files or whole folders onto the window. |
| **Open example** | | Loads the example monkey sculpt (`samples\monkeyGeo.fbx`). |
| **▶ Remesh** | F5 | Runs the seven stages with the current settings on the loaded file. |
| **Compare presets…** | | Pick several presets; they all run on the current file at the same time (up to half your CPU cores). The most accurate run is highlighted green. |
| **■ Cancel** | | Stops the running job immediately. |
| **Export…** | Ctrl+E | Writes the current result (or the original, if you haven't remeshed) in every ticked format. |
| **Batch convert files…** | | Processes every file in the Files list. The app asks: **Yes** remeshes each file with the current settings first, **No** converts them as they are. |
| **Wireframe** | W | Draws the edges on top of the surface. Hidden on meshes above 1.5 million faces (change that in Settings), because it would only look solid black. |
| **Smooth STEP preview** | | Shows the result as the curved patches that the smooth STEP export will write. Works together with Wireframe. |
| **Deviation colours** | H | Colours the result by its distance from the original: blue is close, red is furthest. |
| **Reset view** | R | Fits both models in view. |
| **Settings…** | | Paths to Blender and Instant Meshes, and the wireframe limit. |
| **? Help** | F1 | Opens this guide. |

---

## 3. How a remesh works

Each remesh runs seven stages from top to bottom. Each stage is a box in the settings panel.

```
your sculpt
  │ 1 Cleanup          weld, remove crumbs, fill small holes
  │ 2 Voxel remesh     (optional) rebuild as one closed skin
  │ 3 Smooth bumps     remove noise and small bumps
  │ 4 Reduce           bring the face count down to the target
  │ 5 Quads            triangles become quads
  │ 6 Relax + snap     even out the quads and snap them back onto the surface
  ▼ 7 Measure          compare with the original, fill in the Runs table
clean quad mesh  →  Export: STEP (smooth or flat), STL, OBJ, FBX, GLB, glTF, PLY
```

### What matters most

You can get good results by changing only three things:

1. **Target faces** (stage 4) sets how many quads you get. This controls accuracy, file size and speed.
2. **Smooth bumps → Iterations** (stage 3) sets how much surface noise and sculpting texture is removed.
3. **Snap to** (stage 6) chooses which surface the quads hug: *Smoothed surface* (clean) or *Original sculpt* (faithful, bumps included).

Leave everything else at the preset's values until you have a reason to change it.

---

## 4. Presets

A preset is a saved set of all the settings. Pick one from the **Preset** menu, change anything you like, and press **Save…** to keep your own version. Your presets are stored as plain JSON files (see *Files and folders* below).

| Preset | Use it for |
|---|---|
| **01 Sculpt to CNC - smooth STEP** | The default for organic sculpts going to CAD/CNC. About 4,000 quads, light smoothing, smooth STEP. |
| **02 Max accuracy - dense quads** | When the STEP must follow the sculpt very closely. About 30,000 quads, no smoothing, snapped to the original. Bigger files. |
| **03 Voxel cleanup - old Blender workflow** | Messy models: overlapping subtools, self-intersections, holes. Same idea as voxel remesh in Blender, then cleanup. |
| **04 Remove bumps - strong smoothing** | Sculpts with lots of noise, alpha texture or voxel stair-steps that you don't want to machine. |
| **05 Hard surface - keep creases** | Mechanical or hard-surface models with sharp edges. Feature-preserving smoothing and lower crease angles. |
| **06 Blender QuadriFlow - clean loops** | Cleaner, flowing edge loops. Needs Blender installed. |
| **07 Instant Meshes - field aligned** | Similar to QuadriFlow, using Instant Meshes. Needs Instant Meshes in the tools folder. |
| **08 Fast preview** | A quick, rough look at a new model (about 2,000 quads). |

**Not sure which to use?** Press **Compare presets…**, tick 01, 02, 04 and 08, and let them run together. Then look at the Runs table and the deviation colours.

---

## 5. Every setting explained

This section is the same text you see in the app's tooltips and explanation box.

<!-- settings:start -->
### 1. Cleanup

Repairs the raw model before anything else: duplicate points, floating crumbs, broken spots and small holes. Leave it on unless the model is already clean.

| Setting | What it does | How to set it |
|---|---|---|
| **Enable cleanup** | Runs the repair steps of this section. | Keep it on. Turn it off only to see the model exactly as it was loaded. |
| **Weld distance %** | Points closer together than this are merged into one. Measured as a percentage of the model's overall size (its bounding-box diagonal). | 0 merges only exact duplicates, which is safe. Try 0.01 to 0.05 if the model is split into separate pieces along seams (common after UV splits or some exports). Too high merges details that should stay apart. |
| **Drop pieces smaller than %** | Deletes separate floating pieces smaller than this percentage of the model's size. | 1 removes stray crumbs. Raise it to remove bigger loose bits. Set 0 to keep every piece, for example eyes or teeth that are separate objects. |
| **Close holes up to (edges)** | Fills holes whose rim has at most this many edges. | 100 fills small gaps. Raise it (for example 1000) to cap big openings such as a cut-off neck, which CNC and 3D printing need. 0 leaves all holes open. |

### 2. Voxel remesh

Rebuilds the whole model as one closed skin, the same idea as Blender's voxel remesh. Use it when the model has overlapping pieces (ZBrush subtools), self-intersections or lots of holes. Off by default because it softens fine detail.

| Setting | What it does | How to set it |
|---|---|---|
| **Enable voxel remesh** | Rebuilds the model as one watertight surface on a 3D grid of tiny cubes. | Turn it on for messy models: overlapping subtools, self-intersections, inside faces. Leave it off for clean sculpts, because it loses some fine detail. |
| **Engine** | Which program does the voxel remesh. | Built-in needs nothing extra. Blender (if installed) uses OpenVDB and is faster on huge models. |
| **Voxel size %** | Size of each grid cube, as a percentage of the model's size. | Smaller keeps more detail but is slower and uses more memory. 0.5 is a good start. 0.2 for detailed faces and hands. 1.0 for a quick rough pass. |

### 3. Smooth bumps

Removes noise, voxel stair-steps and small sculpting bumps before the quads are made.

| Setting | What it does | How to set it |
|---|---|---|
| **Method** | How bumps are smoothed out. | Taubin: smooths without shrinking the model; the best general choice. Feature-preserving: keeps sharp creases and edges; use it for hard-surface or mechanical parts. HC Laplacian: very gentle. Off: keep every sculpted detail. |
| **Iterations** | How many smoothing passes to run. | More passes give a smoother surface but lose more detail. 5 to 10 is light, 30 to 60 is strong (clears voxel stair-steps), and above 100 melts details. |
| **Crease angle °** | Feature-preserving smoothing only: where the surface bends more sharply than this angle, it counts as a crease and is kept sharp. | Lower (20 to 30) protects more edges. Higher (60+) smooths more of them away. |

### 4. Reduce

Brings the face count down to roughly the number you ask for. This stage decides how many quads you end up with, so it matters most for file size and speed.

| Setting | What it does | How to set it |
|---|---|---|
| **Method** | How the face count is reduced to the target. | Isotropic remesh: even, regular triangles; these pair into the cleanest quads, so use it for STEP/CNC. Quadric decimation: keeps the most detail per face, but faces are uneven. Off: keeps every face; the result can be huge and STEP export very slow. |
| **Target faces** | Roughly how many faces (quads) you want in the result. | This is the main size control. For CNC/STEP, 2,000 to 10,000 usually looks smooth and accurate (smooth STEP surfaces fill in the curves). For STL printing, 50,000 to 300,000 keeps fine detail. Check the Mean dev column: if it barely improves when you double this number, the lower number is enough. |
| **Isotropic iterations** | Isotropic remesh only: how many passes are used to even out the triangles. | 6 is good. More gives slightly more even faces and takes longer. |
| **Keep open borders** | Keeps the edges of open holes exactly where they are. | Keep it on for open models (a mask, a relief panel) so their outline doesn't shrink. It has no effect on closed models. |

### 5. Quads

Turns the triangles into quads. Smooth STEP export needs 100% quads.

| Setting | What it does | How to set it |
|---|---|---|
| **Method** | How triangles become quads. | Pair + split (built-in): always 100% quads, fast, no extra software; the default. Pair: quad-dominant with some triangles left, fewer faces. Blender QuadriFlow / Instant Meshes: flowing edge loops with fewer poles, but they need Blender or Instant Meshes installed. Keep triangles: no quads (fine for STL only). |
| **Don't pair across °** | Two triangles are never merged into one quad across a fold sharper than this angle. | Lower (20 to 30) keeps hard edges as quad borders, which is good for mechanical parts. Higher allows more pairs on organic shapes. |
| **QuadriFlow: keep sharp** | Blender QuadriFlow only: tries to keep edge loops along sharp edges. | Turn it on for hard-surface models. |
| **QuadriFlow: use symmetry** | Blender QuadriFlow only: makes the quad layout mirror-symmetric (X axis). | Turn it on for symmetric characters whose middle is on X = 0. |
| **Instant Meshes crease °** | Instant Meshes only: edges sharper than this angle are kept as edge loops. | 0 is off. Try 30 to 45 for hard-surface parts. |
| **Instant Meshes smoothing** | Instant Meshes only: how many smoothing passes its direction field gets. | 2 is the default. Higher gives smoother, straighter loops. |

### 6. Relax + snap

Evens out the quads so they are similar in size, and snaps every corner back onto the surface after each step. This keeps the shape accurate.

| Setting | What it does | How to set it |
|---|---|---|
| **Relax iterations** | How many times the quads are evened out. After each pass every point is snapped back onto the surface. | 3 to 8 is typical. 0 skips relaxing (the points are still snapped once). More makes squarer, more even quads. |
| **Relax strength** | How far each point moves per relax pass (0 = not at all, 1 = fully). | 0.5 is balanced. Lower is gentler on fine detail. |
| **Snap to** | Which surface the quads are snapped onto. | Smoothed surface keeps the bumps you removed in step 3 away. Original sculpt hugs the raw model, bumps included, for the most faithful copy. Don't snap leaves points where the quad step put them (fastest, least accurate). |

### 7. Measure

Compares the result with the original and fills in the Runs table, so you can judge settings by numbers instead of by eye.

| Setting | What it does | How to set it |
|---|---|---|
| **Measure accuracy** | After each run, measures how far the result is from the original. | Keep it on: the Runs table and the deviation colours need it. |
| **Samples** | How many surface points are compared for the accuracy numbers. | 60,000 is precise enough. Raise it for very large, detailed models, or lower it to save a second or two. |

### Export settings

| Setting | What it does | How to set it |
|---|---|---|
| **Formats** | Which file types are written when you press Export. Each one goes into the folder you choose. | STEP: CAD/CAM and CNC (exact surfaces). STL: 3D printing and most CAM. OBJ and FBX: other 3D apps, quads kept. GLB/glTF: web and game engines. PLY: scanning and point tools. |
| **STEP surfaces** | How the faces are written into the STEP file. | Smooth surfaces: every quad becomes a curved patch; neighbouring patches meet exactly; best for CNC, needs 100% quads. Flat faces, quads kept: flat facets like the mesh. Flat triangles: the most compatible with old software, but the biggest files. |
| **STEP units** | The unit written into the STEP file. Coordinates are not converted. | Pick the unit your model was made in. To convert, use Scale on export as well (for example cm to mm: unit MM and scale 10). |
| **Smooth: crease above °** | Smooth STEP only: where neighbouring quads meet at a sharper angle than this, the edge stays a crisp crease instead of being rounded. | 50 suits organic models. Use 20 to 30 to keep more hard edges on mechanical parts. |
| **Scale on export** | Multiplies every coordinate when exporting. | 1 keeps the size. 10 turns cm into mm, 25.4 turns inches into mm, 0.1 turns mm into cm. |

### The Runs table

| Column | Meaning |
|---|---|
| **Faces** | Number of faces in the result. |
| **Quads %** | Share of faces that are quads. Smooth STEP needs 100. |
| **Irregular %** | Points that don't have exactly 4 edges (poles). Lower means cleaner edge flow. Built-in methods give about 15; QuadriFlow and Instant Meshes usually give under 10. |
| **Angle dev °** | Average distance of quad corners from a perfect 90°. Under 15 is good. |
| **Mean dev %** | Average distance between the result and the original, as a % of model size. The main accuracy number. For CNC, under 0.02% is excellent. |
| **95% dev %** | 95% of the surface is closer to the original than this. |
| **Max dev %** | The single worst spot. Often a thin tip or a deep crease. |
| **Mean dev** | The average distance in model units (for example mm). |
| **Time s** | How long the run took. |
<!-- settings:end -->

---

## 6. Recipes

**Sculpt to CNC (most common).** Preset 01. If the STEP looks faceted on curves, raise **Target faces** (try 8,000). If the machined surface would show sculpting texture you don't want, raise **Smooth bumps → Iterations** to 20 to 40.

**The STEP must match the sculpt as closely as possible.** Preset 02, or preset 01 with **Snap to = Original sculpt** and **Smooth → Off**. Raise **Target faces** until *Mean dev %* in the Runs table stops improving much.

**ZBrush model with many subtools or self-intersections.** Preset 03 (voxel). Lower **Voxel size %** (0.2) for faces and hands, raise it (0.8) for quick tests.

**Hard-surface or mechanical part.** Preset 05. Set **Smooth: crease above °** in Export to 25 to 35 so sharp edges stay crisp in STEP.

**3D printing (STL).** Any preset with **Target faces** 50,000 to 300,000, or skip remeshing and export the original as STL. STL only stores triangles, so quads are split on export.

**Convert many files without remeshing.** Drop them all in the Files list, tick the formats you want, press **Batch convert files…** and answer **No** (convert as they are).

**cm to mm, or inches to mm.** Keep **STEP units = MM** and set **Scale on export** to 10 (from cm) or 25.4 (from inches).

---

## 7. Choosing good settings by the numbers

1. Run your first try with a preset.
2. Change **one** setting and run again. Each run is a new row in the Runs table.
3. Compare **Mean dev %** (accuracy), **Faces** (size) and **Irregular %** (edge flow).
4. Click the better row and press **Use these settings** to continue from it.

Rules of thumb for CNC:

- *Mean dev %* below **0.02%** is excellent; below 0.05% is usually fine for organic shapes.
- If doubling **Target faces** improves *Mean dev %* by less than about a quarter, the smaller count is enough.
- A high *Max dev %* with a low *Mean dev %* is usually a single thin tip or deep crease. Turn on **Deviation colours** to find it.
- Smooth STEP is more accurate than the flat mesh you see: in testing, 2,000 smooth patches beat 6,000 flat faces.

---

## 8. STEP output in detail

Every STEP export is one closed solid (an open model, such as a mask, is written as a surface body instead).

- **Smooth surfaces**: each quad becomes one curved patch. Neighbouring patches share the exact same border curve, so there are no gaps. Needs 100% quads; all built-in quad methods give that.
- **Flat faces, quads kept**: flat facets. Twisted quads become one exact bilinear face.
- **Flat triangles**: the most compatible with older software, but the largest files.

**Size and speed.** STEP files are big compared with STL. As a guide: 4,000 smooth quads write in under a second (about 6 MB); 650,000 take about 25 seconds (about 1 GB). Above 100,000 faces the app asks first and offers **Skip STEP, export the rest**. For CNC you almost never need more than 20,000 quads.

**Units.** *STEP units* only labels the numbers; it doesn't convert them. Use *Scale on export* to convert.

---

## 9. Optional extra tools

The app works on its own. Two free tools add extra quad methods:

- **Blender** (3.x to 5.x): enables *Blender QuadriFlow* and the *Blender OpenVDB* voxel engine. Blender is found automatically in `C:\Program Files\Blender Foundation`. Otherwise set its path in **Settings…**.
- **Instant Meshes**: download `Instant Meshes.exe` and put it in the `tools` folder next to the app (or in `%APPDATA%\StepConverter\tools`), or set its path in **Settings…**.

---

## 10. Files and folders

| What | Where |
|---|---|
| Bundled presets | `presets\` next to the app |
| Your saved presets | `%APPDATA%\StepConverter\presets` (installer and .exe), or `presets\` in the cloned folder |
| App settings | `%USERPROFILE%\.stepfable.json` |
| Optional tools | `tools\` next to the app, or `%APPDATA%\StepConverter\tools` |
| Example models | `samples\` |

---

## 11. Troubleshooting

**Remesh or export is slow.** Check **Reduce**: if it is *Off*, every original face is kept (a ZBrush mesh can have millions). Set *Isotropic remesh* and a sensible **Target faces**. Very large inputs (several million faces) take a while in the Cleanup and Reduce stages; use preset 08 for a quick look first.

**I don't see the wireframe.** The model probably has more faces than the wireframe limit (1.5 million by default), or it is so dense that the lines merge into black. Remesh first, or raise the limit in **Settings…**.

**Smooth STEP export says it needs quads.** Choose a quad method other than *Keep triangles* or *Pair*, for example *Pair + split*.

**The result has holes or missing pieces.** Raise **Close holes up to (edges)**, lower **Drop pieces smaller than %**, or use the voxel preset (03).

**The result shrank or lost detail.** Lower **Smooth bumps → Iterations**, set **Snap to = Original sculpt**, or raise **Target faces**.

**Blender QuadriFlow or Instant Meshes fails.** Check the path in **Settings…**. QuadriFlow can fail on models with holes or several separate pieces; try the voxel preset first, or use *Pair + split*.

**FBX looks rotated or the wrong size.** FBX files store their own axis and unit settings; Step Converter applies each object's transform. Use **Scale on export** to fix the size. Materials, rigs and animation are not imported.

**Windows SmartScreen warns about the download.** The app isn't code-signed yet. Click *More info* → *Run anyway*.

---

## 12. Command line

The cloned version also has a command line for scripts and batch jobs:

```
stepfable-cli remesh  in.fbx  out.step out.stl --preset "presets\01 Sculpt to CNC - smooth STEP.json" --set target_faces=5000
stepfable-cli convert in.obj  out.glb out.fbx
```

Options: `--step-mode smooth|auto|triangles`, `--unit MM|CM|M|INCH`, `--scale 10`, `--report report.json` (writes the accuracy numbers).
