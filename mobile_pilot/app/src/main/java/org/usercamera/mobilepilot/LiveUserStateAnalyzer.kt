package org.usercamera.mobilepilot

import android.content.Context
import android.graphics.Bitmap
import android.graphics.Matrix
import android.os.SystemClock
import androidx.camera.core.ImageProxy
import com.google.mediapipe.framework.image.BitmapImageBuilder
import com.google.mediapipe.tasks.core.BaseOptions
import com.google.mediapipe.tasks.vision.core.RunningMode
import com.google.mediapipe.tasks.vision.facelandmarker.FaceLandmarker
import java.util.concurrent.atomic.AtomicBoolean
import kotlin.math.*

/** No returned detection confidence / per-eye visibility in FaceLandmarker: keep them null. */
class LiveUserStateAnalyzer(context: Context, private val store: SessionStore, private val quality: (String) -> Unit) {
    private val busy = AtomicBoolean(false)
    private var captureNs: Long? = null
    private var arrivalNs = 0L
    private var startedNs = 0L
    private var lastMs = -1L
    private var meanLuma = 0.0
    private val task = FaceLandmarker.createFromOptions(context, FaceLandmarker.FaceLandmarkerOptions.builder()
        .setBaseOptions(BaseOptions.builder().setModelAssetPath("face_landmarker.task").build())
        .setRunningMode(RunningMode.LIVE_STREAM).setNumFaces(2)
        .setOutputFacialTransformationMatrixes(true).setOutputFaceBlendshapes(true)
        .setResultListener { result, image ->
            try {
                val now = SystemClock.elapsedRealtimeNanos(); val faces = result.faceLandmarks()
                val row = json("timestamp_ns" to captureNs, "arrival_elapsed_ns" to arrivalNs, "available_ns" to now,
                    "inference_latency_ns" to now-startedNs, "face_count" to faces.size, "face_present" to faces.isNotEmpty(),
                    "inference_confidence" to null, "eye_landmark_visibility" to null,
                    "confidence_note" to "FaceLandmarker returns thresholds, not per-inference detection probability",
                    "mapping_status" to if(captureNs == null) "unverified" else "sensor_mapping_estimate_or_shared_clock",
                    "mean_luma" to meanLuma, "distance_kind" to "relative_face_scale_not_mm")
                if(faces.isNotEmpty()) {
                    val points = faces[0]; val xs = points.map { it.x().toDouble() }; val ys = points.map { it.y().toDouble() }
                    val eyes = listOf(33,133,159,145,362,263,386,374).map { points[it] }
                    val eyeFraction = eyes.count { it.x() in 0f..1f && it.y() in 0f..1f } / 8.0
                    val full = xs.min() > .02 && xs.max() < .98 && ys.min() > .02 && ys.max() < .98
                    row.put("face_scale", xs.max()-xs.min()).put("head_x", points[1].x()).put("head_y", points[1].y())
                        .put("eye_in_frame_fraction_proxy", eyeFraction).put("face_fully_in_frame_proxy", full)
                    result.facialTransformationMatrixes().ifPresent { matrices -> if(matrices.isNotEmpty()) {
                        val m = matrices[0] // column-major 4x4 canonical-face transform, proxy only
                        row.put("yaw_proxy_deg", atan2(m[8].toDouble(),m[10].toDouble())*180/PI)
                            .put("pitch_proxy_deg", atan2(-m[9].toDouble(),sqrt(m[8]*m[8]+m[10]*m[10].toDouble()))*180/PI)
                            .put("roll_proxy_deg", atan2(m[1].toDouble(),m[5].toDouble())*180/PI)
                            .put("pose_convention", "canonical_face_column_major_yxz_proxy_not_validated_angles")
                    } }
                    result.faceBlendshapes().ifPresent { values -> if(values.isNotEmpty()) values[0].filter { it.categoryName() in listOf("eyeBlinkLeft","eyeBlinkRight") }.forEach { row.put(it.categoryName(),it.score()) } }
                    quality(if(faces.size>1) "多人入镜，请仅保留一人" else if(!full || eyeFraction<1) "请调整持机角度，使脸部和双眼完整入镜" else if(meanLuma<45) "光照不足，请改善照明" else "面部与双眼在画面内（代理检查）；方向请人工确认")
                } else quality("未检测到人脸，请调整姿态和光照")
                store.stream("live_face_features.jsonl",row)
            } finally { image.close(); busy.set(false) }
        }.setErrorListener { error -> store.event("live_face_error",error.toString()); busy.set(false) }.build())
    fun analyze(proxy: ImageProxy, mappedNs: Long?, arrival: Long) {
        if(!busy.compareAndSet(false,true)) return
        try {
            val ms = arrival/1_000_000L; if(ms<=lastMs) { busy.set(false); return }; lastMs=ms
            val y = proxy.planes[0].buffer.duplicate(); var sum=0L; var n=0; while(y.hasRemaining()) { sum += y.get().toInt() and 255; n++ }; meanLuma=if(n>0) sum.toDouble()/n else 0.0
            val raw=proxy.toBitmap(); val matrix=Matrix().apply { postRotate(proxy.imageInfo.rotationDegrees.toFloat()) }
            val upright=Bitmap.createBitmap(raw,0,0,raw.width,raw.height,matrix,true)
            captureNs=mappedNs;arrivalNs=arrival;startedNs=SystemClock.elapsedRealtimeNanos()
            task.detectAsync(BitmapImageBuilder(upright).build(),ms)
        } catch(e: Exception) { busy.set(false); store.event("live_face_error",e.toString()) }
    }
    fun close() { task.close() }
}

/** Runtime contract: caller passes only observations available by decisionNs. No model shipped. */
fun requireCausalObservation(captureNs: Long, availableNs: Long, decisionNs: Long) {
    require(captureNs >= 0 && availableNs >= captureNs && captureNs <= decisionNs && availableNs <= decisionNs) { "Future or unavailable observation rejected" }
}
interface DifficultyPredictor {
    fun predictDifficulty(userStateHistory: List<org.json.JSONObject>, uiHistory: List<org.json.JSONObject>, actionHistory: List<org.json.JSONObject>, decisionNs: Long): Double?
}
class UntrainedDifficultyPredictor : DifficultyPredictor {
    override fun predictDifficulty(userStateHistory: List<org.json.JSONObject>, uiHistory: List<org.json.JSONObject>, actionHistory: List<org.json.JSONObject>, decisionNs: Long): Double? {
        (userStateHistory+uiHistory+actionHistory).forEach {
            require(it.has("timestamp_ns") && !it.isNull("timestamp_ns")) { "Unmapped capture timestamp rejected" }
            requireCausalObservation(it.getLong("timestamp_ns"),it.optLong("available_ns",it.getLong("timestamp_ns")),decisionNs)
        }
        return null
    }
}
