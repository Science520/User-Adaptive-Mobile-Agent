# MPIIFaceGaze out-of-bounds audit

Independent raw parsing: 37667 valid rows; 243 outside continuous display; 0 additional outside pixel-center extent; 59 exactly on continuous boundaries.

| Subject | N | Outside | Rate % | Bad days |
|---|---:|---:|---:|---|
| p00 | 2927 | 0 | 0.0000 |  |
| p01 | 2904 | 0 | 0.0000 |  |
| p02 | 2916 | 5 | 0.1715 | day21:5 |
| p03 | 2929 | 0 | 0.0000 |  |
| p04 | 2860 | 0 | 0.0000 |  |
| p05 | 2870 | 0 | 0.0000 |  |
| p06 | 2877 | 0 | 0.0000 |  |
| p07 | 2843 | 228 | 8.0197 | day02:11, day04:6, day06:16, day07:5, day11:15, day12:28, day13:5, day14:8, day15:18, day17:9, day19:17, day21:4, day23:9, day38:31, day47:11, day50:16, day55:8, day56:11 |
| p08 | 2767 | 0 | 0.0000 |  |
| p09 | 2719 | 0 | 0.0000 |  |
| p10 | 2194 | 10 | 0.4558 | day05:10 |
| p11 | 2262 | 0 | 0.0000 |  |
| p12 | 1601 | 0 | 0.0000 |  |
| p13 | 1498 | 0 | 0.0000 |  |
| p14 | 1500 | 0 | 0.0000 |  |

## External source comparison

[pperle source](https://github.com/pperle/gaze-tracking/blob/main/dataset/mpii_face_gaze_errors.py) uses integer truncation and closed `[0,W] x [0,H]`. On all local labels, the ID predicate agrees: True.
Published CSV linked from the pinned README: 243 rows; identical ID set=True; coordinate/size mismatches=0. Source URL and SHA256 are recorded in audit_summary.json.
The original script on this sparse photo tree outputs 2 IDs; positional alignment mismatches 360 images. Its numeric predicate must be distinguished from its file/row alignment assumption.
External README percentages (p02 .043%, p07 8.79%, p10 .39%) do not numerically equal these local FaceGaze annotation percentages. Same affected participants; denominator/version/source of percentage differences unresolved. Its calibrated 2–3 degree results use user-specific gaze calibration and are not zero-shot LOSO comparisons.

## Evidence and unresolved causes

The 243 outliers occupy 20 subject/day pairs. Concentration is observed, but day number is a session identifier, not a calendar date. Screen-configuration changes and label-generation mistakes remain unresolved without independent dated device logs or the affected photos.
The ray reconstruction checks shared 2D/3D calibration consistency only. It cannot establish that either label matches physical fixation. Boundary-only cases are kept separate and never silently deleted.

Distance convention: signed edge margins are positive inside; signed axis excess is negative left/top and positive right/bottom; nearest boundary distance is Euclidean distance to the rectangle for outside points.

Views are ID manifests only. Original images, calibration and labels remain untouched.
