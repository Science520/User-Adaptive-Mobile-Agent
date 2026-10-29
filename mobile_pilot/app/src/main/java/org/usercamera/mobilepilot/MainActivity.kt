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
import androidx.camera.view.PreviewView
import androidx.compose.ui.graphics.Color
import androidx.compose.foundation.background
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
        var repetitions by remember { mutableStateOf("1") }
        var points by remember { mutableStateOf("5") }
        var quick by remember { mutableStateOf(true) }
        var jpeg by remember { mutableStateOf(false) }
        var live by remember { mutableStateOf(true) }
        var preferenceMode by remember { mutableStateOf(false) }
        var manualQuality by remember { mutableStateOf(false) }
        var helpMenu by remember { mutableStateOf(false) }
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
                val r = repetitions.toInt(); require(r in 1..3) { "注视重复次数需1/2/3" }
                val count = points.toInt(); require(count in listOf(5,9,25)) { "注视点数需5/9/25" }
                val mm = distance.takeIf { it.isNotBlank() }?.toDouble()
                require(mm == null || mm.isFinite() && mm > 0) { "独立距离需为正数，或留空" }
                engine.start(participant, session, seed.toInt(), r, mm, withCamera, count, quick, jpeg, live, preferenceMode)
            }
            result.onFailure { engine.message = it.message ?: "开始失败" }; refresh()
        }
        LaunchedEffect(engine.phase) {
            if(engine.phase !in listOf("idle","running","quality")) {
                val expected=engine.store.folder; val page=engine.phase
                window.decorView.postDelayed({
                    if(expected!=null && engine.phase==page && engine.store.folder==expected) {
                        val view=window.decorView
                        if(view.width>0 && view.height>0) {
                            val bitmap=android.graphics.Bitmap.createBitmap(view.width,view.height,android.graphics.Bitmap.Config.ARGB_8888)
                            view.draw(android.graphics.Canvas(bitmap)); engine.store.phaseScreenshot(expected,page,bitmap); bitmap.recycle()
                        }
                    }
                },150)
            }
        }
        Column(Modifier.fillMaxSize().windowInsetsPadding(WindowInsets.safeDrawing).padding(12.dp)) {
            if (!(engine.phase == "running" && engine.writer?.stimulus?.optString("task") == "fixation")) Text("User–Screen Mobile Pilot v2", style = MaterialTheme.typography.titleLarge)
            if (engine.phase != "running") Text(engine.message, style = MaterialTheme.typography.bodySmall)
            when (engine.phase) {
                "idle" -> Column(Modifier.weight(1f).verticalScroll(rememberScrollState())) {
                    Text("仅模拟服务，不使用真实账户或支付。前摄帧仅保存在本机；无网络上传。")
                    OutlinedTextField(participant, { participant = it }, label = { Text("Participant ID（匿名编号）") }, singleLine = true)
                    OutlinedTextField(session, { session = it }, label = { Text("Session ID（禁止覆盖）") }, singleLine = true)
                    Row {
                        OutlinedTextField(seed, { seed = it }, label = { Text("种子") }, modifier = Modifier.weight(1f), singleLine = true)
                        OutlinedTextField(repetitions, { repetitions = it }, label = { Text("重复1/2/3次") }, modifier = Modifier.weight(1f), singleLine = true)
                    }
                    OutlinedTextField(points, { points = it }, label = { Text("注视点数5/9/25") }, singleLine = true)
                    Row { Switch(quick,{quick=it}); Text("Quick Test：5点+9项搜索") }
                    Row { Switch(jpeg,{jpeg=it}); Text("JPEG兼容模式（默认MP4）") }
                    Row { Switch(live,{live=it}); Text("尝试视频+实时人脸特征") }
                    Row { Switch(preferenceMode,{preferenceMode=it}); Text("独立偏好适应模式（随机对照）") }
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
                    val current = engine.writer
                    val fixation = current?.stimulus?.optString("task") == "fixation"
                    if (!fixation) Text("任务 ${engine.searchCompleted + 1}/${engine.searchTotal} · 已完成${engine.searchCompleted}，剩余${engine.searchTotal-engine.searchCompleted}")
                    if (current != null) key(current.id) {
                        AndroidView(factory = { ctx -> StimulusView(ctx, current, engine.store, { valid -> engine.rendered(current, valid) }, { engine.complete(true) }) }, modifier = Modifier.weight(1f).fillMaxWidth().background(Color.White))
                    } else Spacer(Modifier.weight(1f))
                    if (!fixation) Row {
                        Button(onClick = { engine.pause() }) { Text("暂停") }
                        OutlinedButton(onClick = { engine.help(); helpMenu=true }) { Text("请求帮助") }
                        OutlinedButton(onClick = { engine.skip() }) { Text("跳过") }
                        OutlinedButton(onClick = { engine.stop(); refresh() }) { Text("退出") }
                    }
                }
                "quality" -> {
                    Text("采集前检查：仅一人入镜、面部和双眼完整、光照充足、方向正确。预览只在此页显示。")
                    AndroidView(factory = { ctx -> PreviewView(ctx).also { engine.attachPreview(it) } }, modifier=Modifier.weight(1f).fillMaxWidth())
                    Button(onClick={engine.refreshQuality()}) { Text("更新检查状态") }
                    Text(engine.message)
                    Row { Checkbox(manualQuality,{manualQuality=it});Text("人工确认：已检查脸部、双眼、光照和方向（记录为人工检查，非模型验证）") }
                    Button(onClick={engine.acceptQuality(manualQuality)},enabled=engine.deviceSmoke || manualQuality || engine.message.startsWith("面部与双眼在画面内")) { Text(if(engine.deviceSmoke) "功能测试继续（非人脸质量通过声明）" else "确认检查通过，继续") }
                    OutlinedButton(onClick={engine.stop();refresh()}) { Text("退出并保存") }
                }
                "instruction", "break" -> {
                    Text(engine.message)
                    Button(onClick={engine.continueInstructions()}) { Text("准备好了，继续") }
                    OutlinedButton(onClick={engine.stop();refresh()}) { Text("退出并保存") }
                }

                "paused" -> {
                    Text("已暂停，当前未完成trial标记aborted；恢复将用新attempt重做，绝不拼接为连续流。")
                    Button(onClick = { engine.resume() }) { Text("恢复") }
                    Button(onClick = { engine.stop(); refresh() }) { Text("Stop并保存") }
                }
                "starting" -> { Text("正在连接前摄并预热时间映射…"); Button(onClick = { engine.stop(); refresh() }) { Text("Stop") } }
                "feedback" -> {
                    if(engine.deviceSmoke) OutlinedButton(onClick={engine.smokeContinue()}) { Text("功能测试：不填写主观评分，继续") }
                    FeedbackForm { rating, type, wantsHelp, assistance, helpfulness -> engine.feedback(rating, type, wantsHelp, assistance, helpfulness); refresh() }
                }
            }
        }
        if (helpMenu) AlertDialog(onDismissRequest={helpMenu=false},title={Text("选择本次实际帮助")},text={ Column {
            listOf("highlight" to "突出目标", "zoom" to "放大文字", "contrast" to "增加对比度", "enlarge_touch" to "扩大点击区域", "explain" to "解释目标", "none" to "不干预").forEach { (action,label) ->
                TextButton(onClick={engine.deliver(action);helpMenu=false}) {Text(label)}
            }
        } },confirmButton={})
        if (confirmDelete) AlertDialog(onDismissRequest = { confirmDelete = false }, title = { Text("删除这个Session？") },
            text = { Text("将永久删除本机 $selected 下的前摄图片、事件和自评；已导出的ZIP不会删除。") },
            confirmButton = { TextButton(onClick = {
                runCatching { engine.store.deleteSession(selected) }.onFailure { engine.message = "删除失败：${it.message}" }
                confirmDelete = false; refresh()
            }) { Text("删除") } }, dismissButton = { TextButton(onClick = { confirmDelete = false }) { Text("取消") } })
    }
}

@Composable private fun FeedbackForm(onSubmit: (Int, String, Boolean, String, Int) -> Unit) {
    var rating by remember { mutableStateOf(0) }; var type by remember { mutableStateOf("") }
    var helpfulness by remember { mutableStateOf(0) }
    var help by remember { mutableStateOf<Boolean?>(null) }; var assistance by remember { mutableStateOf("") }
    Column(Modifier.fillMaxWidth().verticalScroll(rememberScrollState())) {
        Text("任务后自评（所有问题需主动选择）", style = MaterialTheme.typography.titleMedium)
        Text("1. 这个任务完成起来有多困难？1很容易–5很困难")
        Row { (1..5).forEach { score -> FilterChip(selected = rating == score, onClick = { rating = score }, label = { Text("$score") }) } }
        Text("2. 困难类型（多选；单页搜索不记作navigation）")
        listOf("small_font" to "字体太小", "low_contrast" to "对比度不足", "too_many" to "选项太多", "target_not_found" to "找不到目标", "motor" to "点击不准确", "semantic" to "不理解文字", "next_step" to "不知道下一步", "other" to "其他", "none" to "没有困难").forEach { (key, text) ->
            FilterChip(selected = key in type.split(","), onClick = { val chosen=type.split(",").filter{it.isNotBlank()}.toMutableSet(); if(key == "none") { chosen.clear();chosen.add(key) } else { chosen.remove("none"); if(!chosen.add(key)) chosen.remove(key) };type=chosen.joinToString(",") }, label = { Text(text) })
        }
        Text("3. 你有没有想获得帮助？")
        Row { FilterChip(selected = help == true, onClick = { help = true }, label = { Text("有") }); FilterChip(selected = help == false, onClick = { help = false }, label = { Text("没有") }) }
        Text("4. 更希望哪种帮助？偏好本身不代表帮助有效")
        listOf("zoom" to "放大", "highlight" to "突出显示", "explain" to "解释", "none" to "不需要系统干预").forEach { (key, text) ->
            FilterChip(selected = assistance == key, onClick = { assistance = key }, label = { Text(text) })
        }
        Text("5. 本次帮助有用吗？0=未获得帮助，1–5=无用到有用")
        Row { (0..5).forEach { value -> FilterChip(selected=helpfulness==value,onClick={helpfulness=value},label={Text("$value")}) } }
        Button(onClick = { onSubmit(rating, type, help!!, assistance, helpfulness) }, enabled = rating > 0 && type.isNotEmpty() && help != null && assistance.isNotEmpty()) { Text("提交并继续") }
    }
}

class ExperimentEngine(private val activity: ComponentActivity) {
    val store = SessionStore(activity)
    private val camera = FrontCamera(activity, activity, store)
    private val video = FrontVideoRecorder(activity, activity, store)
    var deviceSmoke=false
        private set
    private var jpegMode=false
    private var liveMode=true
    private var preferenceMode=false
    private var preferred="none"
    private var activeAssistance="none"
    private var initialDelivered=false
    private var interventionActive=false
    private var pausedPhase="running"
    private var qualityAccepted=false
    private var preview: PreviewView? = null
    val searchCompleted: Int get()=specs.take(position).count{it.optString("task")=="visual_search"}
    val searchTotal: Int get()=specs.count{it.optString("task")=="visual_search"}
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
    fun start(participant: String, session: String, seed: Int, repetitions: Int, measuredDistance: Double?, cameraEnabled: Boolean, pointCount: Int=5, quick: Boolean=true, jpeg: Boolean=false, live: Boolean=true, adaptation: Boolean=false) {
        require(phase == "idle")
        activity.window.decorView.clearFocus()
        WindowCompat.getInsetsController(activity.window, activity.window.decorView).hide(WindowInsetsCompat.Type.ime())
        val bytes = activity.assets.open("protocol_v2.json").use { it.readBytes() }; val protocol = JSONObject(String(bytes, Charsets.UTF_8))
        val effectiveSeed = seed xor (participant + "_" + session).hashCode()
        specs = createPlan(protocol, effectiveSeed, repetitions, if(quick) 5 else pointCount, quick)
        store.start(participant, session, effectiveSeed, sha256(bytes), measuredDistance)
        deviceSmoke=participant.startsWith("device_smoke")
        store.event("independent_distance_optional", measuredDistance?.let { "$it mm; entered external measurement, not camera truth" } ?: "not measured")
        position = 0; attempt = 0; withCamera = cameraEnabled; jpegMode=jpeg; liveMode=live; preferenceMode=adaptation; preferred="none"; qualityAccepted=false;
        store.configureVideo(if(jpegMode) "jpeg" else "video"); phase = "starting"
        connectAndBegin()
    }
    private fun connectAndBegin() {
        phase = "starting"
        if (withCamera && !jpegMode) {
            if (!qualityAccepted) { phase="quality"; message="连接前摄预览与人脸检查…" }
            if (video.finalized && preview != null) video.start(liveMode) { status -> if(phase=="quality" || phase=="starting") { message=status; if(qualityAccepted) showInstruction() } }
            else if(qualityAccepted) { video.resume(); showInstruction() }
        } else if(withCamera) camera.start { status -> if(phase=="starting") { message=status; showInstruction() } }
        else {
            store.cameraInfo(json("available" to false, "reason" to "explicit_camera_free_mode", "format" to "jpeg_frame_sequence"))
            message = "前摄缺失：此Session仅UI+Touch，不能用于证明Camera增益"
            handler.postDelayed({ if (phase == "starting") showInstruction() }, 500)
        }
    }
    fun attachPreview(view: PreviewView) { preview=view; video.previewView=view; connectAndBegin() }
    fun refreshQuality() { message=video.qualityText }
    fun acceptQuality(manual:Boolean=false) { if(!video.started) {message="等待视频录制真正Start后再继续";return}; qualityAccepted=true; store.event(if(deviceSmoke) "quality_check_smoke_override" else if(manual) "quality_check_manual_unverified" else "quality_check_proxy_passed",video.qualityText); showInstruction() }
    private fun showInstruction() {
        phase="instruction"
        store.event("ui_phase","instruction")
        message=if(position==0) "接下来屏幕会显示黑色圆点。请自然注视圆点，不需要点击，圆点会自动移动。" else "请在页面中找到指定的文字并点击。遇到困难可以请求帮助。"
        store.event("instruction_page",message)
    }
    fun continueInstructions() { if(phase=="instruction" || phase=="break") nextAttempt() }
    private fun endIntervention() { if(interventionActive) {store.assistance(activeAssistance,"intervention_end");interventionActive=false;activeAssistance="none"} }
    fun smokeContinue() { if(deviceSmoke && phase=="feedback") {store.event("automated_smoke_no_self_report");position++;nextAttempt()} }
    fun skip() { if(phase=="running") { timeout?.let{handler.removeCallbacks(it)};endIntervention();store.finish("skipped",false);writer=null;phase="feedback" } }
    fun deliver(action:String) {
        if(phase!="running") return
        if(interventionActive) store.assistance(activeAssistance,"intervention_end")
        activeAssistance=action;interventionActive=true;store.assistance(action,"intervention_onset");store.assistanceRenderer?.invoke(action)
    }
    private fun nextAttempt() {
        if (position >= specs.size) { stop(); message = "全部trial完成，已本地保存，可导出ZIP"; return }
        attempt++
        val spec=JSONObject(specs[position].toString())
        if(preferenceMode && spec.optString("task")=="visual_search") {
            val arm=Random(spec.optInt("randomization_seed")+position).nextInt(3)
            spec.put("adaptation_arm",listOf("no_help","preferred","other")[arm]).put("preference_known_before_trial",preferred)
            spec.put("initial_assistance",if(arm==0) "none" else if(arm==1) preferred else if(preferred=="highlight") "zoom" else "highlight")
        }
        writer=store.begin(spec,attempt); activeAssistance="none";initialDelivered=false;interventionActive=false; phase="running"
    }
    fun rendered(value: TrialWriter, valid: Boolean) {
        if (writer !== value || phase != "running" || value.onsetNs == 0L) return
        if (!valid) {
            store.finish("aborted_render_invalid"); writer = null; if(jpegMode) camera.stop() else video.pause(); phase = "paused"
            message = "布局尺寸改变或字形超出按钮，本trial已排除；布局稳定后可重做，若持续溢出请调整刺激配置"; return
        }
        if(!initialDelivered && value.stimulus.optString("initial_assistance","none")!="none") { val action=value.stimulus.getString("initial_assistance"); initialDelivered=true;deliver(action) }
        timeout?.let { handler.removeCallbacks(it) }
        timeout = Runnable { if (writer === value && phase == "running") complete(false) }
        val remainingMs = value.stimulus.getLong("timeout_ms") - (SystemClock.elapsedRealtimeNanos() - value.onsetNs) / 1_000_000L
        handler.postDelayed(timeout!!, maxOf(0L, remainingMs))
    }
    fun complete(correct: Boolean) {
        if (phase != "running") return
        timeout?.let { handler.removeCallbacks(it) }
        val fixation = writer?.stimulus?.getString("task") == "fixation"
        if(interventionActive) {store.assistance(activeAssistance,"intervention_end");activeAssistance="none";interventionActive=false}
        val done = store.finish(if (correct || fixation) "completed" else "timeout", if (fixation) null else correct)
        writer = null
        if (done == null) { pause(); return }
        if (done.stimulus.getString("task") == "fixation") { position++; if(position<specs.size && specs[position].getString("task")=="visual_search") showInstruction() else nextAttempt() } else { phase = "feedback";store.event("ui_phase","feedback") }
    }
    fun feedback(rating: Int, type: String, wants: Boolean, assistance: String, helpfulness: Int) {
        store.feedback(rating, type, wants, assistance);store.helpfulness(helpfulness);preferred=assistance;position++; if(searchCompleted>0 && searchCompleted%9==0 && position<specs.size) {phase="break";message="分块休息：已完成${searchCompleted}项，可休息后继续";store.event("block_break")} else nextAttempt()
    }
    fun help() { if (phase == "running") store.touch(json("timestamp_ns" to SystemClock.elapsedRealtimeNanos(), "action" to "help_request")) }
    fun pause() {
        if (phase == "idle" || phase == "paused") return
        pausedPhase=phase
        endIntervention()
        timeout?.let { handler.removeCallbacks(it) }; store.pause(); writer = null; if(jpegMode) camera.stop() else video.pause(); phase = "paused"
    }
    fun resume() { if (phase == "paused") { store.resume(); if(!jpegMode && !video.finalized) {video.resume();if(pausedPhase=="feedback") phase="feedback" else showInstruction()} else connectAndBegin() } }
    fun stop() { timeout?.let { handler.removeCallbacks(it) };endIntervention();store.event("task_video_stop_request");video.stop();store.stop(); writer = null; camera.stop(); phase = "idle" }
    fun destroy() { if (phase != "idle") stop(); camera.destroy();video.close() }
    private fun createPlan(protocol: JSONObject, seed: Int, repeats: Int, pointCount: Int, quick: Boolean): List<JSONObject> {
        val array = protocol.getJSONArray("trials"); val all = (0 until array.length()).map { JSONObject(array.getJSONObject(it).toString()) }
        val fixation = all.filter { it.getString("task") == "fixation" }.distinctBy { it.getJSONArray("target_position_px").toString() }.sortedWith(compareBy({it.getJSONArray("target_position_px").getDouble(1)},{it.getJSONArray("target_position_px").getDouble(0)}))
        val selected = if(pointCount==25) fixation else if(pointCount==9) fixation.filterIndexed {i,_ -> i/5 in listOf(0,2,4) && i%5 in listOf(0,2,4)} else fixation.filterIndexed{i,_ -> i in listOf(0,4,12,20,24)}
        val a = (0 until repeats).flatMap { rep -> selected.shuffled(Random(seed + rep)).mapIndexed { i, src ->
            JSONObject(src.toString()).put("trial_id", "A_r%02d_p%02d".format(rep, i)).also { it.getJSONObject("conditions").put("repeat", rep) }
        } }
        val b = all.filter { it.getString("task") == "visual_search" }.let{if(quick) it.take(9) else it}.shuffled(Random(seed)).map { t ->
            t.put("randomization_seed",seed)
        }
        return a + b
    }
}
