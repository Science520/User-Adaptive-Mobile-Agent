package org.usercamera.mobilepilot

import android.content.Context
import android.graphics.ImageFormat
import android.graphics.Rect
import android.graphics.YuvImage
import android.hardware.camera2.CameraCharacteristics
import android.os.SystemClock
import android.util.Size
import androidx.camera.camera2.interop.Camera2CameraInfo
import androidx.camera.core.CameraSelector
import androidx.camera.core.ImageAnalysis
import androidx.camera.core.ImageProxy
import androidx.camera.lifecycle.ProcessCameraProvider
import androidx.core.content.ContextCompat
import androidx.lifecycle.LifecycleOwner
import java.io.ByteArrayOutputStream
import java.util.concurrent.Executors

/** One ImageAnalysis use case records timestamped JPEGs. No MP4/PTS or untested video+analysis combination. */
@androidx.annotation.OptIn(markerClass = [androidx.camera.camera2.interop.ExperimentalCamera2Interop::class])
class FrontCamera(private val context: Context, private val owner: LifecycleOwner, private val store: SessionStore) {
    private val executor = Executors.newSingleThreadExecutor()
    private var provider: ProcessCameraProvider? = null
    @Volatile private var generation = 0
    private var frameIndex = 0
    private var lastSavedSensorNs = Long.MIN_VALUE
    fun start(onReady: (String) -> Unit) {
        val currentGeneration = ++generation
        val future = ProcessCameraProvider.getInstance(context)
        future.addListener({
            if (generation != currentGeneration) return@addListener
            try {
                provider = future.get()
                require(provider!!.hasCamera(CameraSelector.DEFAULT_FRONT_CAMERA)) { "设备无可用前摄" }
                val analysis = ImageAnalysis.Builder().setTargetResolution(Size(640, 480))
                    .setBackpressureStrategy(ImageAnalysis.STRATEGY_KEEP_ONLY_LATEST).build()
                provider!!.unbindAll()
                val camera = provider!!.bindToLifecycle(owner, CameraSelector.DEFAULT_FRONT_CAMERA, analysis)
                val info = Camera2CameraInfo.from(camera.cameraInfo)
                val source = info.getCameraCharacteristic(CameraCharacteristics.SENSOR_INFO_TIMESTAMP_SOURCE)
                val realtime = source == CameraCharacteristics.SENSOR_INFO_TIMESTAMP_SOURCE_REALTIME
                val orientation = info.getCameraCharacteristic(CameraCharacteristics.SENSOR_ORIENTATION)
                val mapper = CameraClockMapper(realtime)
                frameIndex = 0; lastSavedSensorNs = Long.MIN_VALUE
                store.cameraInfo(json("available" to true, "format" to "jpeg_frame_sequence", "target_saved_fps" to 10,
                    "sensor_timestamp_source" to if (realtime) "REALTIME" else "UNKNOWN", "sensor_orientation_degrees" to orientation,
                    "lens_facing" to "front", "raw_frames_mirrored" to false, "exact_driver_dropped_frames" to null,
                    "backpressure" to "KEEP_ONLY_LATEST", "video_plus_analysis_capability" to "not_requested; ImageAnalysis only"))
                camera.cameraInfo.cameraState.observe(owner) { state ->
                    if (generation == currentGeneration) store.event("camera_state", "${state.type}; error=${state.error?.code}")
                }
                analysis.setAnalyzer(executor) { image ->
                    try {
                        val arrival = SystemClock.elapsedRealtimeNanos(); val sensor = image.imageInfo.timestamp
                        mapper.observe(sensor, arrival)
                        val writer = store.trial
                        if (generation != currentGeneration || writer == null || writer.onsetNs == 0L) return@setAnalyzer
                        val mapped = mapper.mapped(sensor)
                        val before = mapped != null && mapped < writer.onsetNs
                        val save = !before && (lastSavedSensorNs == Long.MIN_VALUE || sensor - lastSavedSensorNs >= 100_000_000L)
                        val row = json("frame_id" to frameIndex++, "sensor_timestamp_ns" to sensor,
                            "arrival_elapsed_ns" to arrival, "mapped_timestamp_ns" to mapped,
                            "clock_source" to if (realtime) "REALTIME" else "UNKNOWN", "mapping_status" to mapper.status(),
                            "sync_uncertainty_ns" to if (realtime) 0 else null,
                            "clock_mapping" to json("validated" to false, "offset_ns" to mapper.offsetNs,
                                "validation_method" to "arrival_lower_envelope_only", "arrival_offset_spread_ns" to mapper.arrivalOffsetSpreadNs(),
                                "unidentifiable_minimum_capture_latency" to true),
                            "rotation_degrees" to image.imageInfo.rotationDegrees, "width" to image.width, "height" to image.height,
                            "status" to if (before) "pre_onset" else if (save) "recorded" else "sampled_out")
                        val jpeg = if (save) imageToJpeg(image) else null
                        if (save) lastSavedSensorNs = sensor
                        store.cameraFrame(writer, row, jpeg)
                    } catch (e: Exception) { store.event("camera_analysis_error", e.javaClass.simpleName + ":" + e.message) }
                    finally { image.close() }
                }
                // Allow UNKNOWN offset estimation to collect warmup anchors before first trial. Still unvalidated.
                android.os.Handler(android.os.Looper.getMainLooper()).postDelayed({
                    if (generation == currentGeneration) onReady(if (realtime) "前摄已连接，REALTIME共同时间基准" else "前摄已连接，UNKNOWN时钟仅有偏移估计，融合分析需独立验证")
                }, 1500)
            } catch (e: Exception) {
                store.cameraInfo(json("available" to false, "error" to e.javaClass.simpleName, "message" to e.message, "format" to "jpeg_frame_sequence"))
                store.event("camera_unavailable", e.message ?: "unknown")
                onReady("前摄不可用：${e.message}；本Session明确标记camera缺失")
            }
        }, ContextCompat.getMainExecutor(context))
    }
    fun stop() { generation++; provider?.unbindAll() }
    fun destroy() { stop(); executor.shutdown() }
    private fun imageToJpeg(image: ImageProxy): ByteArray {
        require(image.format == ImageFormat.YUV_420_888)
        val w = image.width; val h = image.height; val data = ByteArray(w * h * 3 / 2)
        var out = 0
        val y = image.planes[0]; val u = image.planes[1]; val v = image.planes[2]
        val yb = y.buffer.duplicate(); val ub = u.buffer.duplicate(); val vb = v.buffer.duplicate()
        val yBase = yb.position(); val uBase = ub.position(); val vBase = vb.position()
        for (row in 0 until h) for (col in 0 until w) data[out++] = yb.get(yBase + row * y.rowStride + col * y.pixelStride)
        for (row in 0 until h / 2) for (col in 0 until w / 2) {
            data[out++] = vb.get(vBase + row * v.rowStride + col * v.pixelStride)
            data[out++] = ub.get(uBase + row * u.rowStride + col * u.pixelStride)
        }
        return ByteArrayOutputStream().use { bytes ->
            require(YuvImage(data, ImageFormat.NV21, w, h, null).compressToJpeg(Rect(0, 0, w, h), 85, bytes))
            bytes.toByteArray()
        }
    }
}
