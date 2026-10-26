# MPII expansion: fixed-test sample-size comparison

same original360 test IDs and original24 validation IDs per fold; only training changes 312->624

| Model | Original test360 angular mean° | Screen mean mm | New test360 angular mean° (separate cohort) |
|---|---:|---:|---:|
| frozen_224_ridge_original360 | 12.463 | 91.03 | 11.733 |
| frozen_224_ridge_expanded720 | 12.176 | 88.18 | 11.688 |
| finetuned_64_original360 | 12.049 | 83.20 | not computed (exact old control has no saved checkpoint) |
| finetuned_64_expanded720 | 11.351 | 77.91 | 11.264 |

{
  "frozen_224_ridge": {
    "mean_left_minus_right": -0.2877297572427147,
    "ci95": [
      -0.5550741760037943,
      -0.006940944172336064
    ],
    "note": "paired participant bootstrap of fixed OOF predictions, descriptive; no retraining inside bootstrap"
  },
  "finetuned_64": {
    "mean_left_minus_right": -0.6985632341169091,
    "ci95": [
      -1.2285103773131296,
      -0.04911145351741404
    ],
    "note": "paired participant bootstrap of fixed OOF predictions, descriptive; no retraining inside bootstrap"
  }
}

Negative paired delta means expanded training lowers error on the SAME original360 test IDs. Bootstrap is descriptive, no repeated training.
New test360 results measure changed test composition, not model improvement. No gaze-specific pretrained weights. No synchronized mobile/difficulty evidence.
Neural executed: True. Resource estimate is in neural_resource_estimate.json. Original v1 manifests, processed files, caches and reports preserved.
