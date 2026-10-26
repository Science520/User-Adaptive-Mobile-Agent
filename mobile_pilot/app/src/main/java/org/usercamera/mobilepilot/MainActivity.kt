package org.usercamera.mobilepilot

import android.Manifest
import android.content.pm.PackageManager
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.os.SystemClock
import android.view.WindowManager
import androidx.activity.ComponentActivity
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.compose.setContent
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.compose.ui.viewinterop.AndroidView
import androidx.core.content.ContextCompat
import androidx.core.view.WindowCompat
import androidx.core.view.WindowInsetsCompat
import org.json.JSONArray
import org.json.JSONObject
import java.time.LocalDateTime
import java.time.format.DateTimeFormatter
import java.util.concurrent.Executors
import kotlin.random.Random

class MainActivity : ComponentActivity() {
    private lateinit var engine: ExperimentEngine
    private val fileExecutor = Executors.newSingleThreadExecutor()
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        engine = ExperimentEngine(this)
        setContent { MaterialTheme { PilotScreen() } }
    }
    override fun onPause() { if (::engine.isInitialized) engine.pause(); super.onPause() }
    override fun onDestroy() { engine.destroy(); fileExecutor.shutdown(); super.onDestroy() }

    @Composable private fun PilotScreen() {
        var participant by remember { mutableStateOf("") }
        var session by remember { mutableStateOf(LocalDateTime.now().format(DateTimeFormatter.ofPattern("yyyyMMdd_HHmmss"))) }
        var seed by remember { mutableStateOf("42") }
        var repetitions by remember { mutableStateOf("2") }
        var distance by remember { mutableStateOf("") }
        var entries by remember { mutableStateOf(engine.store.listSessions()) }
        var selected by remember { mutableStateOf(entries.firstOrNull() ?: "") }
        var confirmDelete by remember { mutableStateOf(false) }
        var busyExport by remember { mutableStateOf(false) }
        val permission = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) { granted ->
            engine.message = if (granted) "相机已授权，可以开始" else "相机权限被拒绝；可选择无相机开始，camera将标记缺失"
        }
        val exporter = rememberLauncherForActivityResult(ActivityResultContracts.CreateDocument("application/zip")) { uri ->
            if (uri != null) {
                busyExport = true; val id = selected
                fileExecutor.execute {
                    val result = runCatching { contentResolver.openOutputStream(uri)?.use { engine.store.export(id, it) } ?: error("无法写入导出位置") }
                    runOnUiThread { busyExport = false; engine.message = result.fold({ "已导出Session ZIP：$id" }, { "导出失败：${it.message}" }) }
                }
            }
        }
        fun refresh() { entries = engine.store.listSessions(); selected = entries.firstOrNull() ?: "" }
        fun start(withCamera: Boolean) {
            val result = runCatching {
                val r = repetitions.toInt(); require(r in 2..3) { "注视重复次数需2或3" }
                val mm = distance.takeIf { it.isNotBlank() }?.toDouble()
                require(mm == null || mm.isFinite() && mm > 0) { "独立距离需为正数，或留空" }
                engine.start(participant, session, seed.toInt(), r, mm, withCamera)
            }
            result.onFailure { engine.message = it.message ?: "开始失败" }; refresh()
        }
        Column(Modifier.fillMaxSize().windowInsetsPadding(WindowInsets.safeDrawing).padding(12.dp)) {
            Text("User–Screen Mobile Pilot", style = MaterialTheme.typography.titleLarge)
            Text(engine.message, style = MaterialTheme.typography.bodySmall)
            when (engine.phase) {
                "idle" -> Column(Modifier.weight(1f).verticalScroll(rememberScrollState())) {
                    Text("仅模拟服务，不使用真实账户或支付。前摄帧仅保存在本机；无网络上传。")
                    OutlinedTextField(participant, { participant = it }, label = { Text("Participant ID（匿名编号）") }, singleLine = true)
                    OutlinedTextField(session, { session = it }, label = { Text("Session ID（禁止覆盖）") }, singleLine = true)
                    Row {
                        OutlinedTextField(seed, { seed = it }, label = { Text("种子") }, modifier = Modifier.weight(1f), singleLine = true)
                        OutlinedTextField(repetitions, { repetitions = it }, label = { Text("注视重复2–3次") }, modifier = Modifier.weight(1f), singleLine = true)
                    }
                    OutlinedTextField(distance, { distance = it }, label = { Text("独立量具测得距离mm（可留空，非相机估计）") }, singleLine = true)
                    Button(onClick = {
                        if (ContextCompat.checkSelfPermission(this@MainActivity, Manifest.permission.CAMERA) != PackageManager.PERMISSION_GRANTED) permission.launch(Manifest.permission.CAMERA)
                        else start(true)
                    }) { Text("Start Experiment（前摄）") }
                    OutlinedButton(onClick = { start(false) }) { Text("明确无相机开始（仅UI与触摸）") }
                    Text("已保存Session（点击选择）")
                    entries.forEach { id -> TextButton(onClick = { selected = id }) { Text((if (id == selected) "✓ " else "") + id) } }
                    Row {
                        Button(onClick = { exporter.launch("$selected.zip") }, enabled = selected.isNotEmpty() && !busyExport) { Text("导出ZIP") }
                        OutlinedButton(onClick = { confirmDelete = true }, enabled = selected.isNotEmpty() && !busyExport) { Text("删除Session") }
                    }
                    if (busyExport) Text("正在校验并导出，请稍候")
                }
                "running" -> {
                    Text("Trial ${engine.position + 1}/${engine.total} · ${engine.writer?.id ?: "等待绘制"}")
                    val current = engine.writer
                    if (current != null) key(current.id) {
                        AndroidView(factory = { ctx -> StimulusView(ctx, current, engine.store, { valid -> engine.rendered(current, valid) }, { engine.complete(true) }) }, modifier = Modifier.weight(1f).fillMaxWidth())
                    } else Spacer(Modifier.weight(1f))
                    Row {
                        Button(onClick = { engine.pause() }) { Text("Pause") }
                        OutlinedButton(onClick = { engine.help() }) { Text("希望帮助（仅记录）") }
                        OutlinedButton(onClick = { engine.stop(); refresh() }) { Text("Stop") }
                    }
                }
                "paused" -> {
                    Text("已暂停，当前未完成trial标记aborted；恢复将用新attempt重做，绝不拼接为连续流。")
                    Button(onClick = { engine.resume() }) { Text("恢复") }
                    Button(onClick = { engine.stop(); refresh() }) { Text("Stop并保存") }
                }
                "starting" -> { Text("正在连接前摄并预热时间映射…"); Button(onClick = { engine.stop(); refresh() }) { Text("Stop") } }
                "feedback" -> FeedbackForm { rating, type, wantsHelp, assistance -> engine.feedback(rating, type, wantsHelp, assistance); refresh() }
            }
        }
        if (confirmDelete) AlertDialog(onDismissRequest = { confirmDelete = false }, title = { Text("删除这个Session？") },
            text = { Text("将永久删除本机 $selected 下的前摄图片、事件和自评；已导出的ZIP不会删除。") },
            confirmButton = { TextButton(onClick = {
                runCatching { engine.store.deleteSession(selected) }.onFailure { engine.message = "删除失败：${it.message}" }
                confirmDelete = false; refresh()
            }) { Text("删除") } }, dismissButton = { TextButton(onClick = { confirmDelete = false }) { Text("取消") } })
    }
}

@Composable private fun FeedbackForm(onSubmit: (Int, String, Boolean, String) -> Unit) {
    var rating by remember { mutableStateOf(0) }; var type by remember { mutableStateOf("") }
    var help by remember { mutableStateOf<Boolean?>(null) }; var assistance by remember { mutableStateOf("") }
    Column(Modifier.fillMaxWidth().verticalScroll(rememberScrollState())) {
        Text("任务后自评（所有问题需主动选择）", style = MaterialTheme.typography.titleMedium)
        Text("1. 这个任务完成起来有多困难？1很容易–5很困难")
        Row { (1..5).forEach { score -> FilterChip(selected = rating == score, onClick = { rating = score }, label = { Text("$score") }) } }
        Text("2. 主要困难是什么？")
        listOf("visual" to "视觉", "motor" to "点击精度", "navigation" to "导航", "semantic" to "理解", "none" to "没有").forEach { (key, text) ->
            FilterChip(selected = type == key, onClick = { type = key }, label = { Text(text) })
        }
        Text("3. 你有没有想获得帮助？")
        Row { FilterChip(selected = help == true, onClick = { help = true }, label = { Text("有") }); FilterChip(selected = help == false, onClick = { help = false }, label = { Text("没有") }) }
        Text("4. 更希望哪种帮助？这是偏好记录，本轮不实施干预")
        listOf("zoom" to "放大", "highlight" to "突出显示", "explain" to "解释", "none" to "不需要系统干预").forEach { (key, text) ->
            FilterChip(selected = assistance == key, onClick = { assistance = key }, label = { Text(text) })
        }
        Button(onClick = { onSubmit(rating, type, help!!, assistance) }, enabled = rating > 0 && type.isNotEmpty() && help != null && assistance.isNotEmpty()) { Text("提交并继续") }
    }
}

class ExperimentEngine(private val activity: ComponentActivity) {
    val store = SessionStore(activity)
    private val camera = FrontCamera(activity, activity, store)
    private val handler = Handler(Looper.getMainLooper())
    var phase by mutableStateOf("idle")
        private set
    var message by mutableStateOf("原型待真机验证；仅操作本实验App，默认不上传人脸图片")
    var writer by mutableStateOf<TrialWriter?>(null)
        private set
    var position by mutableStateOf(0)
        private set
    val total: Int get() = specs.size
    private var specs = listOf<JSONObject>()
    private var attempt = 0
    private var withCamera = true
    private var timeout: Runnable? = null
    fun start(participant: String, session: String, seed: Int, repetitions: Int, measuredDistance: Double?, cameraEnabled: Boolean) {
        require(phase == "idle")
        activity.window.decorView.clearFocus()
        WindowCompat.getInsetsController(activity.window, activity.window.decorView).hide(WindowInsetsCompat.Type.ime())
        val bytes = activity.assets.open("protocol.json").use { it.readBytes() }; val protocol = JSONObject(String(bytes, Charsets.UTF_8))
        val effectiveSeed = seed xor (participant + "_" + session).hashCode()
        specs = createPlan(protocol, effectiveSeed, repetitions)
        store.start(participant, session, effectiveSeed, sha256(bytes), measuredDistance)
        store.event("independent_distance_optional", measuredDistance?.let { "$it mm; entered external measurement, not camera truth" } ?: "not measured")
        position = 0; attempt = 0; withCamera = cameraEnabled; phase = "starting"
        connectAndBegin()
    }
    private fun connectAndBegin() {
        phase = "starting"
        if (withCamera) camera.start { status -> if (phase == "starting") { message = status; nextAttempt() } }
        else {
            store.cameraInfo(json("available" to false, "reason" to "explicit_camera_free_mode", "format" to "jpeg_frame_sequence"))
            message = "前摄缺失：此Session仅UI+Touch，不能用于证明Camera增益"
            handler.postDelayed({ if (phase == "starting") nextAttempt() }, 500)
        }
    }
    private fun nextAttempt() {
        if (position >= specs.size) { stop(); message = "全部trial完成，已本地保存，可导出ZIP"; return }
        attempt++; writer = store.begin(specs[position], attempt); phase = "running"
    }
    fun rendered(value: TrialWriter, valid: Boolean) {
        if (writer !== value || phase != "running" || value.onsetNs == 0L) return
        if (!valid) {
            store.finish("aborted_render_invalid"); writer = null; camera.stop(); phase = "paused"
            message = "布局尺寸改变或字形超出按钮，本trial已排除；布局稳定后可重做，若持续溢出请调整刺激配置"; return
        }
        timeout?.let { handler.removeCallbacks(it) }
        timeout = Runnable { if (writer === value && phase == "running") complete(false) }
        val remainingMs = value.stimulus.getLong("timeout_ms") - (SystemClock.elapsedRealtimeNanos() - value.onsetNs) / 1_000_000L
        handler.postDelayed(timeout!!, maxOf(0L, remainingMs))
    }
    fun complete(correct: Boolean) {
        if (phase != "running") return
        timeout?.let { handler.removeCallbacks(it) }
        val fixation = writer?.stimulus?.getString("task") == "fixation"
        val done = store.finish(if (correct || fixation) "completed" else "timeout", if (fixation) null else correct)
        writer = null
        if (done == null) { pause(); return }
        if (done.stimulus.getString("task") == "fixation") { position++; nextAttempt() } else phase = "feedback"
    }
    fun feedback(rating: Int, type: String, wants: Boolean, assistance: String) {
        store.feedback(rating, type, wants, assistance); position++; nextAttempt()
    }
    fun help() { if (phase == "running") store.touch(json("timestamp_ns" to SystemClock.elapsedRealtimeNanos(), "action" to "help_request")) }
    fun pause() {
        if (phase != "running" && phase != "starting") return
        timeout?.let { handler.removeCallbacks(it) }; store.pause(); writer = null; camera.stop(); phase = "paused"
    }
    fun resume() { if (phase == "paused") { store.resume(); connectAndBegin() } }
    fun stop() { timeout?.let { handler.removeCallbacks(it) }; store.stop(); writer = null; camera.stop(); phase = "idle" }
    fun destroy() { if (phase != "idle") stop(); camera.destroy() }
    private fun createPlan(protocol: JSONObject, seed: Int, repeats: Int): List<JSONObject> {
        val array = protocol.getJSONArray("trials"); val all = (0 until array.length()).map { JSONObject(array.getJSONObject(it).toString()) }
        val fixation = all.filter { it.getString("task") == "fixation" }.distinctBy { it.getJSONArray("target_position_px").toString() }
        val a = (0 until repeats).flatMap { rep -> fixation.shuffled(Random(seed + rep)).mapIndexed { i, src ->
            JSONObject(src.toString()).put("trial_id", "A_r%02d_p%02d".format(rep, i)).also { it.getJSONObject("conditions").put("repeat", rep) }
        } }
        val b = all.filter { it.getString("task") == "visual_search" }.shuffled(Random(seed)).mapIndexed { i, t ->
            val elements = t.getJSONArray("elements")
            val distractors = (0 until elements.length()).filter { elements.getJSONObject(it).getString("role") == "distractor" }
            val words = distractors.map { elements.getJSONObject(it).getString("text") to elements.getJSONObject(it).getJSONArray("text_lines") }.shuffled(Random(seed + i + 1000))
            distractors.forEachIndexed { j, idx -> elements.getJSONObject(idx).put("text", words[j].first).put("text_lines", JSONArray(words[j].second.toString())) }
            val identity = json("elements" to elements, "target" to t.getString("target_element_id"), "instruction" to t.getString("instruction"), "conditions" to t.getJSONObject("conditions"))
            t.put("template_id", sha256(identity.toString().toByteArray(Charsets.UTF_8)))
        }
        return a + b
    }
}
