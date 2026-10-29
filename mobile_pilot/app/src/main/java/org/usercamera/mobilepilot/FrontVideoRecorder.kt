package org.usercamera.mobilepilot

import android.content.Context
import android.hardware.camera2.CameraCharacteristics
import android.media.MediaExtractor
import android.media.MediaFormat
import android.os.SystemClock
import android.util.Range
import android.util.Size
import androidx.camera.camera2.interop.Camera2CameraInfo
import androidx.camera.core.*
import androidx.camera.lifecycle.ProcessCameraProvider
import androidx.camera.video.*
import androidx.camera.view.PreviewView
import androidx.core.content.ContextCompat
import androidx.lifecycle.LifecycleOwner
import java.io.File
import java.util.concurrent.Executors

/** Hardware encoder owns video. Analysis is a separate KEEP_ONLY_LATEST consumer, never JPEG writing. */
@androidx.annotation.OptIn(markerClass = [androidx.camera.camera2.interop.ExperimentalCamera2Interop::class])
class FrontVideoRecorder(private val context: Context, private val owner: LifecycleOwner, private val store: SessionStore) {
    private var provider: ProcessCameraProvider? = null
    private var recording: Recording? = null
    private val analysisExecutor = Executors.newSingleThreadExecutor()
    private val diskExecutor = Executors.newSingleThreadExecutor()
    private var analyzer: LiveUserStateAnalyzer? = null
    var previewView: PreviewView? = null
    var qualityText: String = "等待人脸检查"
    private var generation = 0
    private var segment = 0
    private var pendingReady: ((String) -> Unit)? = null
    private var requestedStop = false
    private var closing=false
    var started=false
        private set
    var finalized = true
        private set

    fun start(enableAnalysis: Boolean, onReady: (String) -> Unit) {
        val token = ++generation; requestedStop = false;started=false; pendingReady = onReady
        val future = ProcessCameraProvider.getInstance(context)
        future.addListener({
            if (token != generation) return@addListener
            try {
                provider = future.get(); provider!!.unbindAll()
                val recorder = Recorder.Builder().setQualitySelector(QualitySelector.from(Quality.HD,
                    FallbackStrategy.lowerQualityOrHigherThan(Quality.HD))).build()
                val video = VideoCapture.Builder(recorder).setTargetFrameRate(Range(24, 30)).build()
                val preview = Preview.Builder().build().also { previewView?.let { view -> it.setSurfaceProvider(view.surfaceProvider) } }
                val analysis = ImageAnalysis.Builder().setTargetResolution(Size(640, 480))
                    .setBackpressureStrategy(ImageAnalysis.STRATEGY_KEEP_ONLY_LATEST).build()
                analyzer = if (enableAnalysis) runCatching { LiveUserStateAnalyzer(context, store) { qualityText = it } }.onFailure{store.event("live_analyzer_unavailable",it.toString())}.getOrNull() else null
                val useCases = mutableListOf<UseCase>(preview, video)
                if (analyzer != null) useCases.add(analysis)
                var combined = analyzer != null
                val camera = try { provider!!.bindToLifecycle(owner, CameraSelector.DEFAULT_FRONT_CAMERA, *useCases.toTypedArray()) }
                catch (e: Exception) {
                    store.event("video_analysis_bind_fallback", e.toString()); combined = false
                    analyzer?.close(); analyzer = null; provider!!.unbindAll()
                    provider!!.bindToLifecycle(owner, CameraSelector.DEFAULT_FRONT_CAMERA, preview, video)
                }
                val info = Camera2CameraInfo.from(camera.cameraInfo)
                val source = info.getCameraCharacteristic(CameraCharacteristics.SENSOR_INFO_TIMESTAMP_SOURCE)
                val mapper = CameraClockMapper(source == CameraCharacteristics.SENSOR_INFO_TIMESTAMP_SOURCE_REALTIME)
                if (combined) analysis.setAnalyzer(analysisExecutor) { image ->
                    try {
                        val arrival = SystemClock.elapsedRealtimeNanos(); mapper.observe(image.imageInfo.timestamp, arrival)
                        val timestamp = mapper.mapped(image.imageInfo.timestamp)
                        store.stream("video_timeline.jsonl", json("type" to "analysis_sensor_frame", "timestamp_ns" to arrival,
                            "sensor_timestamp_ns" to image.imageInfo.timestamp, "mapped_timestamp_ns" to timestamp,
                            "mapping_status" to mapper.status(), "rotation_degrees" to image.imageInfo.rotationDegrees,
                            "not_a_video_pts_pair" to true))
                        analyzer?.analyze(image, timestamp, arrival)
                    } catch (e: Exception) { store.event("live_analysis_error", e.toString()) }
                    finally { image.close() }
                }
                store.cameraInfo(json("available" to true, "format" to "h264_mp4", "audio_enabled" to false,
                    "target_fps_range" to org.json.JSONArray(listOf(24,30)), "video_plus_analysis_capability" to if (combined) "bound_pending_device_measurement" else "video_only",
                    "live_features" to if (combined) "enabled" else "unavailable_offline_required", "lens_facing" to "front",
                    "raw_frames_mirrored" to false, "preview_mirrored" to true,
                    "sensor_timestamp_source" to if (mapper.realtime) "REALTIME" else "UNKNOWN",
                    "sensor_orientation_degrees" to info.getCameraCharacteristic(CameraCharacteristics.SENSOR_ORIENTATION),
                    "pts_elapsed_mapping" to "estimated_unverified"))
                val dir = store.folder!!; val file = File(dir, if (!File(dir,"front_camera.mp4").exists()) "front_camera.mp4" else "front_camera_%03d.mp4".format(segment))
                segment++; require(!file.exists())
                File(dir, "video_pending").writeText("awaiting Finalize")
                finalized = false
                val requestNs = SystemClock.elapsedRealtimeNanos()
                recording = recorder.prepareRecording(context, FileOutputOptions.Builder(file).build()).start(ContextCompat.getMainExecutor(context)) { event ->
                    val now = SystemClock.elapsedRealtimeNanos()
                    val type = when(event) { is VideoRecordEvent.Start -> "start"; is VideoRecordEvent.Pause -> "pause"; is VideoRecordEvent.Resume -> "resume"; is VideoRecordEvent.Finalize -> "finalize"; else -> "status" }
                    val row = json("type" to type, "timestamp_ns" to now, "path" to file.name,
                        "recording_request_ns" to requestNs, "recorded_duration_ns" to event.recordingStats.recordedDurationNanos,
                        "bytes" to event.recordingStats.numBytesRecorded, "mapping_status" to "estimated_unverified",
                        "sync_uncertainty_ns" to null, "timeline_reference" to "Recorder callback arrival and accumulated recorded duration; not capture anchor")
                    if (event is VideoRecordEvent.Finalize) {
                        row.put("error_code", event.error).put("finalization_success", !event.hasError()).put("cause", event.cause?.toString())
                        recording = null;started=false
                        diskExecutor.execute {
                            try { inspect(file) } catch (e: Exception) { store.stream("video_timeline.jsonl", json("type" to "inspection_error", "timestamp_ns" to SystemClock.elapsedRealtimeNanos(), "error" to e.toString())) }
                            File(dir, "video_pending").delete(); finalized = true
                            if(closing) diskExecutor.shutdown()
                            provider?.let { p -> ContextCompat.getMainExecutor(context).execute { if (requestedStop) p.unbindAll() } }
                        }
                    }
                    store.stream("video_timeline.jsonl", row)
                    if (event is VideoRecordEvent.Start) { started=true;pendingReady?.invoke("视频录制已开始；PTS映射尚未独立验证"); pendingReady = null; if (requestedStop) recording?.stop() }
                }
            } catch (e: Exception) {
                store.cameraInfo(json("available" to false, "format" to "h264_mp4", "error" to e.toString()))
                onReady("视频不可用：${e.message}；请停止并选JPEG兼容模式"); pendingReady = null
            }
        }, ContextCompat.getMainExecutor(context))
    }
    private fun inspect(file: File) {
        val extractor = MediaExtractor(); extractor.setDataSource(file.path)
        try {
            val index = (0 until extractor.trackCount).first { extractor.getTrackFormat(it).getString(MediaFormat.KEY_MIME)?.startsWith("video/") == true }
            val format = extractor.getTrackFormat(index); extractor.selectTrack(index)
            val encodedRows=mutableListOf<org.json.JSONObject>()
            var count = 0; var first = -1L; var last = -1L; var gaps = 0; var maxGap = 0L
            do {
                val pts = extractor.sampleTime; if (pts < 0) break
                if (first < 0) first = pts
                if (last >= 0) { val delta = pts-last; maxGap = maxOf(maxGap, delta); if (delta > 75000) gaps++ }
                encodedRows.add(json("type" to "encoded_frame", "path" to file.name, "frame_index" to count,
                    "pts_us" to pts, "flags" to extractor.sampleFlags, "mapped_elapsed_ns" to null,
                    "mapping_status" to "unverified", "sync_uncertainty_ns" to null))
                count++; last = pts
            } while (extractor.advance())
            store.streamBatch("video_timeline.jsonl",encodedRows)
            store.stream("video_timeline.jsonl", json("type" to "file_summary", "timestamp_ns" to SystemClock.elapsedRealtimeNanos(),
                "path" to file.name, "sha256" to fileSha256(file), "bytes" to file.length(), "frame_count" to count,
                "first_pts_us" to first, "last_pts_us" to last, "effective_fps" to if(last>first) (count-1)*1e6/(last-first) else null,
                "gap_count_over_75ms" to gaps, "maximum_pts_gap_us" to maxGap, "exact_dropped_frames" to null,
                "width" to format.getInteger(MediaFormat.KEY_WIDTH), "height" to format.getInteger(MediaFormat.KEY_HEIGHT),
                "rotation_degrees" to if(format.containsKey(MediaFormat.KEY_ROTATION)) format.getInteger(MediaFormat.KEY_ROTATION) else 0,
                "mime" to format.getString(MediaFormat.KEY_MIME), "encoder_format" to format.toString(), "mirrored" to false))
        } finally { extractor.release() }
    }
    fun pause() { recording?.pause() }
    fun resume() { recording?.resume() }
    fun stop() { requestedStop = true; generation++; recording?.stop(); if (finalized) provider?.unbindAll() }
    fun close() { closing=true;stop(); analyzer?.close(); analysisExecutor.shutdown(); if(finalized) diskExecutor.shutdown() }
}
