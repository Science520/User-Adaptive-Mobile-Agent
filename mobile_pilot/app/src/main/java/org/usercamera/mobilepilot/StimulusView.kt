package org.usercamera.mobilepilot

import android.annotation.SuppressLint
import android.content.Context
import android.graphics.Bitmap
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.graphics.Rect
import android.graphics.RectF
import android.os.SystemClock
import android.view.MotionEvent
import android.view.View
import org.json.JSONArray
import org.json.JSONObject

@SuppressLint("ViewConstructor")
class StimulusView(context: Context, private val writer: TrialWriter, private val store: SessionStore,
    private val onRendered: (Boolean) -> Unit, private val onCorrect: () -> Unit) : View(context) {
    private val paint = Paint(Paint.ANTI_ALIAS_FLAG)
    private var submitted = false
    private var uiVersion = 0
    private var assistance = writer.stimulus.optString("initial_assistance","none")
    private fun effect(): String = assistanceEffect(assistance)
    private var assistanceObserver: ((String) -> Unit)? = null
    init {
        assistanceObserver = { action -> assistance = action; uiVersion++; submitted = false; invalidate() }
        store.assistanceRenderer = assistanceObserver
    }
    override fun onDetachedFromWindow() { if (store.assistanceRenderer === assistanceObserver) store.assistanceRenderer = null; super.onDetachedFromWindow() }
    private var renderValid = true
    private var geometryGeneration = 0
    private val boxes = mutableListOf<Pair<JSONObject, RectF>>()
    private fun explanation(spec: JSONObject): String {
        val elements=spec.getJSONArray("elements")
        val text=(0 until elements.length()).map{elements.getJSONObject(it)}.first{it.getString("element_id")==spec.getString("target_element_id")}.optString("text")
        if(spec.has("target_explanation")) return spec.getString("target_explanation")
        return when(text) {
            "检查预约" -> "安排检查项目的预约时间。此为模拟服务入口。"
            "疫苗接种" -> "查看接种服务信息或预约。此为模拟服务入口。"
            "商品溯源" -> "查看商品来源和流转信息。此为模拟服务入口。"
            "慢病管理" -> "查看长期健康管理服务。此为模拟服务入口。"
            else -> "这是指定服务的模拟入口，点击后完成本轮查找。"
        }
    }
    override fun onSizeChanged(w: Int, h: Int, oldw: Int, oldh: Int) {
        super.onSizeChanged(w, h, oldw, oldh)
        geometryGeneration++
        if (submitted && oldw > 0 && oldh > 0 && writer.active) {
            if (writer.onsetNs == 0L) { submitted = false; invalidate() }
            else {
                store.event("stimulus_layout_changed", "$oldw x $oldh -> $w x $h; abort instead of stale target geometry")
                post { if (writer.active) onRendered(false) }
            }
        }
    }
    override fun onDraw(canvas: Canvas) {
        super.onDraw(canvas)
        val timestamp = SystemClock.elapsedRealtimeNanos(); canvas.drawColor(Color.WHITE)
        val spec = writer.stimulus; val base = spec.getJSONArray("base_size_px")
        val sx = minOf(width / base.getDouble(0).toFloat(), height / base.getDouble(1).toFloat()); val sy = sx
        val dx = (width - base.getDouble(0).toFloat() * sx) / 2f
        val dy = (height - base.getDouble(1).toFloat() * sy) / 2f
        paint.color = Color.BLACK; paint.style = Paint.Style.FILL; paint.textSize = 38 * sx
        paint.textAlign = Paint.Align.LEFT
        if (spec.getString("task") != "fixation") {
            canvas.drawText(spec.getString("instruction"), dx + 36 * sx, dy + 120 * sy, paint)
            if (effect() == "explain") {
                paint.textSize = 27*sx
                canvas.drawText(explanation(spec), dx+36*sx, dy+170*sy,paint)
            }
        }
        val elements=spec.getJSONArray("elements")
        val regions=spec.optJSONArray("regions") ?: JSONArray()
        val targetRegion=(0 until elements.length()).map{elements.getJSONObject(it)}.first{it.optString("role")=="target"}.optString("region_id")
        for(i in 0 until regions.length()) {
            val region=regions.getJSONObject(i);val b=region.getJSONArray("box");val bg=region.getJSONArray("background_rgb")
            val rect=RectF(dx+b.getDouble(0).toFloat()*sx,dy+b.getDouble(1).toFloat()*sy,dx+b.getDouble(2).toFloat()*sx,dy+b.getDouble(3).toFloat()*sy)
            paint.style=Paint.Style.FILL;paint.color=Color.rgb(bg.getInt(0),bg.getInt(1),bg.getInt(2));canvas.drawRoundRect(rect,12*sx,12*sy,paint)
            paint.color=Color.DKGRAY;paint.textSize=24*sx;canvas.drawText(region.getString("label"),rect.left+12*sx,rect.top+34*sy,paint)
            if(effect()=="highlight_region" && region.getString("region_id")==targetRegion) {
                paint.style=Paint.Style.STROKE;paint.strokeWidth=8*sx;paint.color=Color.rgb(20,90,180);canvas.drawRoundRect(rect,12*sx,12*sy,paint)
            }
        }
        val actual = JSONArray(); boxes.clear(); renderValid = true
        for (i in 0 until elements.length()) {
            val original = elements.getJSONObject(i); val e = JSONObject(original.toString())
            e.put("render_timestamp_ns", timestamp)
            fun rect(key: String): RectF { val b = e.getJSONArray(key); return RectF(dx + b.getDouble(0).toFloat() * sx, dy + b.getDouble(1).toFloat() * sy, dx + b.getDouble(2).toFloat() * sx, dy + b.getDouble(3).toFloat() * sy) }
            val box = rect("bounding_box_px"); val click = rect("clickable_region_px")
            val target = e.getString("element_id") == spec.getString("target_element_id")
            if (target && effect() == "enlarge_touch") { click.inset(-12*sx,-12*sy); click.intersect(0f,0f,width.toFloat(),height.toFloat()) }
            e.put("bounding_box_px", JSONArray(listOf(box.left, box.top, box.right, box.bottom)))
            e.put("clickable_region_px", JSONArray(listOf(click.left, click.top, click.right, click.bottom)))
            boxes.add(e to click)
            if (spec.getString("task") == "fixation") {
                paint.color = Color.BLACK; paint.style = Paint.Style.FILL; canvas.drawOval(box, paint)
                e.put("actual_glyph_height_px", box.height())
                val location = IntArray(2); getLocationOnScreen(location)
                e.put("instructed_target_screen_px", JSONArray(listOf(box.centerX() + location[0], box.centerY() + location[1])))
            } else {
                val bg=e.optJSONArray("background_rgb")
                val baseBackground=if(bg==null) Color.WHITE else Color.rgb(bg.getInt(0),bg.getInt(1),bg.getInt(2))
                paint.style=Paint.Style.FILL;paint.color=baseBackground;canvas.drawRoundRect(box,10*sx,10*sy,paint)
                if(target && effect() == "highlight") { paint.style=Paint.Style.FILL; paint.color=Color.YELLOW; canvas.drawRoundRect(box,10*sx,10*sy,paint) }
                paint.style = Paint.Style.STROKE; paint.strokeWidth = maxOf(1f, 2 * sx); paint.color = Color.LTGRAY
                canvas.drawRoundRect(box, 10 * sx, 10 * sy, paint)
                paint.style = Paint.Style.FILL
                val plannedGray = original.getInt("foreground_gray")
                val g = if(effect() == "contrast") 0 else plannedGray
                paint.color = Color.rgb(g, g, g)
                val background = if(target && effect() == "highlight") Color.YELLOW else baseBackground
                e.put("planned_foreground_gray", plannedGray).put("foreground_gray", g)
                    .put("rendered_background_argb", background)
                    .put("visual_contrast", androidx.core.graphics.ColorUtils.calculateContrast(paint.color, background))
                paint.typeface=android.graphics.Typeface.create(android.graphics.Typeface.DEFAULT,if(e.optInt("font_weight",400)>=600) android.graphics.Typeface.BOLD else android.graphics.Typeface.NORMAL)
                val desired = e.getDouble("font_glyph_height_px").toFloat() * sx * if(effect() == "zoom") 1.25f else 1f
                paint.textSize = desired; val glyphBounds = Rect(); val text = e.getString("text")
                repeat(3) { paint.getTextBounds(text, 0, text.length, glyphBounds); paint.textSize *= desired / maxOf(1, glyphBounds.height()) }
                paint.getTextBounds(text, 0, text.length, glyphBounds)
                e.put("actual_glyph_height_px", glyphBounds.height()).put("font_text_size_px", paint.textSize).put("typeface", "Android default sans-serif")
                val lines = JSONArray()
                val plannedLines=e.getJSONArray("text_lines")
                for(j in 0 until plannedLines.length()) {
                    var current=""
                    for(ch in plannedLines.getString(j)) {
                        if(current.isNotEmpty() && paint.measureText(current+ch)>box.width()-12*sx) {lines.put(current);current=""}
                        current+=ch
                    }
                    if(current.isNotEmpty()) lines.put(current)
                }
                e.put("text_lines",lines)
                val inks = JSONArray(); paint.textAlign = Paint.Align.LEFT
                for (line in 0 until lines.length()) {
                    val value = lines.getString(line); val bounds = Rect(); paint.getTextBounds(value, 0, value.length, bounds)
                    val cx = box.centerX(); val cy = box.centerY() + (line - (lines.length() - 1) / 2f) * (desired + 5 * sx)
                    val x = cx - (bounds.left + bounds.right) / 2f; val y = cy - (bounds.top + bounds.bottom) / 2f
                    val ink = RectF(x + bounds.left, y + bounds.top, x + bounds.right, y + bounds.bottom)
                    if (!box.contains(ink) && effect() != "zoom") renderValid = false
                    canvas.drawText(value, x, y, paint); inks.put(JSONArray(listOf(ink.left, ink.top, ink.right, ink.bottom)))
                }
                e.put("ink_bounding_boxes_px", inks)
            }
            if(e.has("icon_id")) {
                paint.style=Paint.Style.FILL;paint.color=Color.rgb(80,110,145)
                val cx=box.left+14*sx;val cy=box.top+14*sy
                val shape=when(e.getString("icon_id")) {"icon_1" -> "square";"icon_2" -> "triangle";else -> "circle"}
                when(shape) {
                    "square" -> canvas.drawRect(cx-6*sx,cy-6*sy,cx+6*sx,cy+6*sy,paint)
                    "triangle" -> { val path=android.graphics.Path().apply{moveTo(cx,cy-7*sy);lineTo(cx-7*sx,cy+6*sy);lineTo(cx+7*sx,cy+6*sy);close()};canvas.drawPath(path,paint) }
                    else -> canvas.drawCircle(cx,cy,6*sx,paint)
                }
                e.put("rendered_icon_shape",shape)
            }
            actual.put(e)
        }
        if(effect() == "enlarge_touch") boxes.sortBy { if(it.first.optString("element_id")==spec.getString("target_element_id")) 0 else 1 }
        if (!submitted) {
            submitted = true
            val generationAtDraw = geometryGeneration
            val versionAtDraw=uiVersion
            val location = IntArray(2); getLocationOnScreen(location)
            val state = json("timestamp_ns" to timestamp, "timestamp_kind" to "draw_callback_submission_not_photon_onset",
                "view_size_px" to JSONArray(listOf(width, height)), "view_origin_screen_px" to JSONArray(location.toList()),
                "protocol_version" to spec.optString("protocol_version","mobile-pilot-rsm-v3"),
                "task_family" to spec.optString("task_family",spec.getString("task")),"research_mode" to spec.optString("research_mode"),
                "assigned_assistance" to spec.optString("assigned_assistance","none"),
                "oracle_target_highlight" to (effect()=="highlight"),
                "highlighted_region_id" to if(effect()=="highlight_region") targetRegion else null,
                "cue_candidate_count" to if(effect()=="highlight_region") (0 until elements.length()).count{elements.getJSONObject(it).optString("region_id")==targetRegion} else null,
                "ui_state_version" to uiVersion, "delivered_assistance" to assistance, "assistance_explanation_text" to if(effect() == "explain") explanation(spec) else null, "coordinate_system" to "view_local_px",
                "page_id" to spec.getString("page_id"), "target_element_id" to spec.getString("target_element_id"),
                "elements" to actual, "screenshot_path" to if(uiVersion == 0) "stimulus.png" else "ui_%03d.png".format(uiVersion), "render_valid" to renderValid)
            post {
                if (generationAtDraw != geometryGeneration || versionAtDraw != uiVersion) return@post
                if (width > 0 && height > 0 && writer.active) {
                    val bitmap = Bitmap.createBitmap(width, height, Bitmap.Config.ARGB_8888); draw(Canvas(bitmap))
                    store.render(writer, state, bitmap); bitmap.recycle(); onRendered(state.getBoolean("render_valid"))
                }
            }
        }
    }
    @SuppressLint("ClickableViewAccessibility")
    override fun onTouchEvent(event: MotionEvent): Boolean {
        if (!writer.active || writer.onsetNs == 0L) return true
        val action = when (event.actionMasked) { MotionEvent.ACTION_DOWN -> "down"; MotionEvent.ACTION_UP -> "up"; MotionEvent.ACTION_CANCEL -> "cancel"; MotionEvent.ACTION_MOVE -> "move"; MotionEvent.ACTION_POINTER_DOWN -> "pointer_down"; MotionEvent.ACTION_POINTER_UP -> "pointer_up"; else -> return true }
        val beforeElapsed = SystemClock.elapsedRealtimeNanos()
        val uptimeNs = SystemClock.uptimeMillis() * 1_000_000L
        val afterElapsed = SystemClock.elapsedRealtimeNanos()
        val offset = beforeElapsed + (afterElapsed - beforeElapsed) / 2L - uptimeNs
        val location = IntArray(2); getLocationOnScreen(location)
        fun record(pointer: Int, history: Int?) {
            val x = if(history == null) event.getX(pointer) else event.getHistoricalX(pointer,history)
            val y = if(history == null) event.getY(pointer) else event.getHistoricalY(pointer,history)
            val time = if(history == null) event.eventTime else event.getHistoricalEventTime(history)
            val hit = boxes.firstOrNull { it.second.contains(x,y) }?.first
            val correct = hit?.optString("element_id") == writer.stimulus.getString("target_element_id")
            store.touch(json("timestamp_ns" to time*1_000_000L+offset, "raw_uptime_ms" to time, "event_clock_offset_ns" to offset,
                "mapping_uncertainty_ns" to (afterElapsed-beforeElapsed)/2L+1_000_000L,
                "action" to if(history != null) "move" else action, "pointer_id" to event.getPointerId(pointer),
                "is_action_pointer" to (pointer == event.actionIndex), "historical" to (history != null),
                "x_px" to x, "y_px" to y, "screen_x_px" to x+location[0], "screen_y_px" to y+location[1],
                "normalized_x" to x/width, "normalized_y" to y/height, "coordinate_system" to "view_local_px_plus_origin_to_screen",
                "view_origin_screen_px" to JSONArray(location.toList()), "page_id" to writer.stimulus.getString("page_id"),
                "protocol_version" to writer.stimulus.optString("protocol_version","mobile-pilot-rsm-v3"),
                "task_family" to writer.stimulus.optString("task_family"),"research_mode" to writer.stimulus.optString("research_mode"),
                "delivered_assistance" to assistance,
                "ui_state_version" to uiVersion, "element_id" to hit?.getString("element_id"),
                "correct_target_hit" to correct, "interaction_success" to if(action == "up" && history == null) correct else null))
        }
        for(h in 0 until event.historySize) for(pointer in 0 until event.pointerCount) record(pointer,h)
        for(pointer in 0 until event.pointerCount) record(pointer,null)
        val correct = boxes.firstOrNull { it.second.contains(event.x,event.y) }?.first?.optString("element_id") == writer.stimulus.getString("target_element_id")
        if (action == "up" && correct && renderValid && writer.stimulus.getString("task") != "fixation") onCorrect()
        return true
    }
}
