package org.usercamera.mobilepilot

import android.content.Context
import android.graphics.Bitmap
import android.os.Build
import android.os.SystemClock
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.io.OutputStream
import java.security.MessageDigest
import java.util.zip.ZipEntry
import java.util.zip.ZipOutputStream

fun json(vararg pairs: Pair<String, Any?>): JSONObject = JSONObject().apply {
    pairs.forEach { (k, v) -> put(k, v ?: JSONObject.NULL) }
}
fun sha256(bytes: ByteArray): String = MessageDigest.getInstance("SHA-256").digest(bytes).joinToString("") { "%02x".format(it.toInt() and 255) }
fun fileSha256(file: File): String {
    val digest = MessageDigest.getInstance("SHA-256")
    file.inputStream().use { input -> val buffer = ByteArray(65536); while (true) { val n = input.read(buffer); if (n < 0) break; digest.update(buffer, 0, n) } }
    return digest.digest().joinToString("") { "%02x".format(it.toInt() and 255) }
}
fun File.writeJson(value: JSONObject) = writeText(value.toString(2))
fun File.appendJson(value: JSONObject) = appendText(value.toString() + "\n")

data class TrialWriter(val id: String, val directory: File, val stimulus: JSONObject, var onsetNs: Long = 0L,
    var clicks: Int = 0, var misclicks: Int = 0, var helpRequests: Int = 0, var active: Boolean = true)

class SessionStore(private val context: Context) {
    private val lock = Any()
    var assistanceRenderer: ((String) -> Unit)? = null
    val sessionsRoot = File(context.filesDir, "sessions").apply { mkdirs() }
    var folder: File? = null
        private set
    private var session: JSONObject? = null
    @Volatile var trial: TrialWriter? = null
        private set
    var lastFinished: TrialWriter? = null
        private set

    fun start(participant: String, sessionId: String, seed: Int, protocolHash: String, measuredDistanceMm: Double? = null) = synchronized(lock) {
        require(Regex("[A-Za-z0-9_-]{1,64}").matches(participant)) { "Participant ID只允许字母、数字、下划线、短横线" }
        require(Regex("[A-Za-z0-9_-]{1,64}").matches(sessionId)) { "Session ID格式不正确" }
        require(folder == null || !File(folder,"video_pending").exists()) { "上一个Session视频仍在Finalize，请稍后开始" }
        val id = participant + "_" + sessionId
        val dir = File(sessionsRoot, id)
        require(!dir.exists()) { "Session已存在，请更换ID，禁止覆盖" }
        dir.mkdirs(); File(dir, "trials").mkdirs(); folder = dir
        val dm = context.resources.displayMetrics
        session = json("schema_version" to "temporal-pilot-v2", "participant_id" to participant,
            "session_id" to id, "evidence_tier" to if(participant.startsWith("device_smoke")) "device_automated_smoke" else "real_device_recording", "clock" to "elapsed_realtime_ns",
            "created_ns" to SystemClock.elapsedRealtimeNanos(), "status" to "running", "trial_ids" to JSONArray(),
            "presentation_seed" to seed, "protocol_sha256" to protocolHash,
            "independent_viewing_distance_mm" to measuredDistanceMm,
            "distance_measurement_source" to if (measuredDistanceMm == null) "not_measured" else "user_entered_external_measurement_unverified",
            "device" to json("model" to "${Build.MANUFACTURER} ${Build.MODEL}", "sdk_int" to Build.VERSION.SDK_INT,
                "screen_size_px" to JSONArray(listOf(dm.widthPixels, dm.heightPixels)), "density" to dm.density,
                "density_dpi" to dm.densityDpi, "font_scale" to context.resources.configuration.fontScale),
            "camera" to json("available" to false, "format" to "jpeg_frame_sequence", "target_saved_fps" to 10,
                "video_plus_analysis_capability" to "not_requested; only ImageAnalysis frame-sequence recording"))
        File(dir, "session_events.jsonl").writeText(""); saveSession(); event("start")
    }
    private fun saveSession() { folder?.let { File(it, "session.json").writeJson(session!!) } }
    fun event(type: String, detail: String = "") = synchronized(lock) {
        if (session?.optString("status") == "stopped" && type != "stop") return@synchronized
        folder?.let { File(it, "session_events.jsonl").appendJson(json("timestamp_ns" to SystemClock.elapsedRealtimeNanos(), "type" to type, "detail" to detail)) }
    }
    fun cameraInfo(info: JSONObject) = synchronized(lock) { session?.put("camera", info); saveSession() }
    fun begin(stimulus: JSONObject, attempt: Int): TrialWriter = synchronized(lock) {
        val id = stimulus.getString("trial_id") + "_attempt$attempt"
        val dir = File(folder, "trials/$id"); require(!dir.exists()); dir.mkdirs(); File(dir, "frames").mkdirs()
        listOf("camera_frames.jsonl", "ui_states.jsonl", "touch_events.jsonl", "assistance_events.jsonl").forEach { File(dir, it).writeText("") }
        File(dir, "feedback.json").writeJson(json("status" to "missing"))
        TrialWriter(id, dir, stimulus).also { trial = it }
    }
    fun render(writer: TrialWriter, ui: JSONObject, bitmap: Bitmap) = synchronized(lock) {
        if (trial !== writer || !writer.active ) return@synchronized
        if (writer.onsetNs == 0L) {
            writer.onsetNs = ui.getLong("timestamp_ns")
            session!!.getJSONArray("trial_ids").put(writer.id); saveSession()
        }
        File(writer.directory, ui.getString("screenshot_path")).outputStream().use { bitmap.compress(Bitmap.CompressFormat.PNG, 100, it) }
        File(writer.directory, "ui_states.jsonl").appendJson(ui)
        stream("ui_states.jsonl", JSONObject(ui.toString()).put("trial_id", writer.id))
    }
    fun touch(value: JSONObject) = synchronized(lock) {
        val t = trial ?: return@synchronized
        if (!t.active || t.onsetNs == 0L) return@synchronized
        File(t.directory, "touch_events.jsonl").appendJson(value)
        stream("touch_events.jsonl", JSONObject(value.toString()).put("trial_id", t.id))
        if (value.getString("action") == "up") { t.clicks++; if (!value.optBoolean("correct_target_hit")) t.misclicks++ }
        if (value.getString("action") == "help_request") t.helpRequests++
    }
    fun cameraFrame(writer: TrialWriter, row: JSONObject, jpeg: ByteArray?) = synchronized(lock) {
        if (trial !== writer || !writer.active || writer.onsetNs == 0L) return@synchronized
        if (jpeg != null) {
            val relative = "frames/%08d.jpg".format(row.getInt("frame_id")); val p = File(writer.directory, relative)
            try {
                p.writeBytes(jpeg); row.put("path", relative).put("sha256", sha256(jpeg))
                    .put("stored_elapsed_ns", SystemClock.elapsedRealtimeNanos())
            } catch (e: Exception) { p.delete(); row.put("status", "write_error").put("error", e.javaClass.simpleName) }
        }
        File(writer.directory, "camera_frames.jsonl").appendJson(row)
    }
    fun finish(status: String, success: Boolean? = null): TrialWriter? = synchronized(lock) {
        val t = trial ?: return@synchronized null; t.active = false; trial = null
        if (t.onsetNs == 0L) { event("aborted_before_first_draw", t.id); t.directory.deleteRecursively(); return@synchronized null }
        val offset = SystemClock.elapsedRealtimeNanos(); val s = session!!
        File(t.directory, "trial_meta.json").writeJson(json("trial_id" to t.id, "participant_id" to s.getString("participant_id"),
            "session_id" to s.getString("session_id"), "task" to t.stimulus.getString("task"),
            "template_id" to t.stimulus.getString("template_id"), "onset_ns" to t.onsetNs, "offset_ns" to offset,
            "onset_timestamp_kind" to "first_draw_callback_submission_not_photon_onset", "status" to status, "stimulus" to t.stimulus,
            "pair_id" to t.stimulus.optString("pair_id"), "condition_id" to t.stimulus.optString("condition_id"),
            "outcome" to json("success" to success, "completion_time_ms" to (offset - t.onsetNs) / 1e6,
                "misclicks" to t.misclicks, "help_requests" to t.helpRequests)))
        if (t.stimulus.getString("task") == "fixation" || status.startsWith("aborted")) File(t.directory, "feedback.json").writeJson(json("status" to "not_applicable"))
        lastFinished = t; t
    }
    fun feedback(rating: Int, type: String, wantsHelp: Boolean, assistance: String) = synchronized(lock) {
        val t = lastFinished ?: return@synchronized
        File(t.directory, "feedback.json").writeJson(json("status" to "provided", "label_source" to "self_report",
            "timestamp_ns" to SystemClock.elapsedRealtimeNanos(), "difficulty_rating" to rating, "difficulty_type" to type, "difficulty_types" to JSONArray(type.split(",")),
            "wants_help" to wantsHelp, "preferred_assistance" to assistance))
        event("feedback", t.id)
    }
    fun pause() = synchronized(lock) { finish("aborted_pause"); session?.put("status", "paused"); event("pause"); saveSession() }
    fun resume() = synchronized(lock) { session?.put("status", "running"); event("resume"); saveSession() }
    fun stop() = synchronized(lock) { finish("aborted_stop"); session?.put("status", "stopped")?.put("stopped_ns", SystemClock.elapsedRealtimeNanos()); event("stop"); saveSession() }

    fun phaseScreenshot(expectedFolder: File, phase: String, bitmap: Bitmap) = synchronized(lock) {
        if(folder != expectedFolder || session?.optString("status") == "stopped") return@synchronized
        val timestamp=SystemClock.elapsedRealtimeNanos(); val path="page_${timestamp}.png"
        File(expectedFolder,path).outputStream().use { bitmap.compress(Bitmap.CompressFormat.PNG,100,it) }
        stream("ui_states.jsonl", json("timestamp_ns" to timestamp,"page_id" to phase,"trial_id" to JSONObject.NULL,
            "ui_state_version" to timestamp,"timestamp_kind" to "decor_draw_snapshot_not_photon_onset",
            "screenshot_path" to path,"view_size_px" to JSONArray(listOf(bitmap.width,bitmap.height)),
            "view_origin_screen_px" to JSONArray(listOf(0,0)),"elements" to JSONArray()))
    }
    fun stream(name: String, value: JSONObject) = synchronized(lock) {
        require(name in listOf("video_timeline.jsonl", "ui_states.jsonl", "touch_events.jsonl", "live_face_features.jsonl", "assistance_events.jsonl"))
        folder?.let { File(it, name).appendJson(value) }
    }
    fun streamBatch(name: String, values: List<JSONObject>) = synchronized(lock) {
        require(name == "video_timeline.jsonl")
        java.io.BufferedWriter(java.io.OutputStreamWriter(java.io.FileOutputStream(File(folder,name),true),Charsets.UTF_8),65536).use { out -> values.forEach {out.write(it.toString());out.newLine()} }
    }
    fun configureVideo(mode: String) = synchronized(lock) {
        session?.put("screen_recording_mode", "reconstructed_ui_timeline")?.put("capture_mode", mode)
        listOf("video_timeline.jsonl", "ui_states.jsonl", "touch_events.jsonl", "live_face_features.jsonl", "assistance_events.jsonl").forEach { File(folder, it).writeText("") }
        saveSession()
    }
    fun assistance(action: String, type: String) = synchronized(lock) {
        val t = trial ?: lastFinished ?: return@synchronized
        val row = json("timestamp_ns" to SystemClock.elapsedRealtimeNanos(), "trial_id" to t.id, "type" to type,
            "requested_action" to action, "delivered_action" to action)
        File(t.directory, "assistance_events.jsonl").appendJson(row); stream("assistance_events.jsonl", row)
    }
    fun helpfulness(rating: Int) = synchronized(lock) {
        lastFinished?.let { val p = File(it.directory, "feedback.json"); val value = JSONObject(p.readText()); value.put("helpfulness_rating", rating); p.writeJson(value) }
    }
    fun listSessions(): List<String> = sessionsRoot.listFiles()?.filter { it.isDirectory }?.map { it.name }?.sortedDescending() ?: emptyList()
    fun deleteSession(id: String) = synchronized(lock) {
        val p = File(sessionsRoot, id); require(p.canonicalFile.parentFile == sessionsRoot.canonicalFile)
        require(trial == null) { "先停止实验再删除" }; require(p.deleteRecursively()) { "删除失败" }
        if (p == folder) { folder = null; session = null }
    }
    fun export(id: String, output: OutputStream) = synchronized(lock) {
        require(trial == null) { "先停止实验再导出" }
        val dir = File(sessionsRoot, id); require(dir.canonicalFile.parentFile == sessionsRoot.canonicalFile && dir.isDirectory)
        require(!File(dir, "video_pending").exists()) { "等待视频Finalize后再导出" }
        val files = dir.walkTopDown().filter { it.isFile && it.name != "export_manifest.json" }.sortedBy { it.relativeTo(dir).path }.toList()
        val records = JSONArray(); files.forEach { records.put(json("path" to it.relativeTo(dir).invariantSeparatorsPath, "bytes" to it.length(), "sha256" to fileSha256(it))) }
        File(dir, "export_manifest.json").writeJson(json("files" to records))
        ZipOutputStream(output).use { zip ->
            (files + File(dir, "export_manifest.json")).forEach { file ->
                zip.putNextEntry(ZipEntry(file.relativeTo(dir).invariantSeparatorsPath)); file.inputStream().use { it.copyTo(zip) }; zip.closeEntry()
            }
        }
    }
}
