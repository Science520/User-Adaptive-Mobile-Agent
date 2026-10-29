# Offline Face Landmarker asset

`app/src/main/assets/face_landmarker.task` is copied from the project's existing local `data/models/face_landmarker.task`; no new dataset download was performed. Android needs the bundled asset for offline LIVE_STREAM inference; it is a public model, not a participant image or personalized model.

Official model source: [MediaPipe Face Landmarker](https://ai.google.dev/edge/mediapipe/solutions/vision/face_landmarker#models).
Original download URL already recorded in `reports/pilot/reference_downloads.json`:
`https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task`.

SHA256 is included in the current [build verification](../reports/pilot_v2/build_verification.json). Dependencies' license notices remain in the Gradle artifacts/APK. The final merged Manifest explicitly removes INTERNET and ACCESS_NETWORK_STATE introduced by transitive dependencies, and does not request RECORD_AUDIO.
