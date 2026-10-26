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
    private var renderValid = true
    private var geometryGeneration = 0
    private val boxes = mutableListOf<Pair<JSONObject, RectF>>()
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
        paint.textAlign = Paint.Align.LEFT; canvas.drawText(spec.getString("instruction"), dx + 36 * sx, dy + 120 * sy, paint)
        val elements = spec.getJSONArray("elements"); val actual = JSONArray(); boxes.clear(); renderValid = true
        for (i in 0 until elements.length()) {
            val original = elements.getJSONObject(i); val e = JSONObject(original.toString())
            e.put("render_timestamp_ns", timestamp)
            fun rect(key: String): RectF { val b = e.getJSONArray(key); return RectF(dx + b.getDouble(0).toFloat() * sx, dy + b.getDouble(1).toFloat() * sy, dx + b.getDouble(2).toFloat() * sx, dy + b.getDouble(3).toFloat() * sy) }
            val box = rect("bounding_box_px"); val click = rect("clickable_region_px")
            e.put("bounding_box_px", JSONArray(listOf(box.left, box.top, box.right, box.bottom)))
            e.put("clickable_region_px", JSONArray(listOf(click.left, click.top, click.right, click.bottom)))
            boxes.add(e to click)
            if (spec.getString("task") == "fixation") {
                paint.color = Color.BLACK; paint.style = Paint.Style.FILL; canvas.drawOval(box, paint)
                e.put("actual_glyph_height_px", box.height())
                val location = IntArray(2); getLocationOnScreen(location)
                e.put("instructed_target_screen_px", JSONArray(listOf(box.centerX() + location[0], box.centerY() + location[1])))
            } else {
                paint.style = Paint.Style.STROKE; paint.strokeWidth = maxOf(1f, 2 * sx); paint.color = Color.LTGRAY
                canvas.drawRoundRect(box, 10 * sx, 10 * sy, paint)
                paint.style = Paint.Style.FILL; val g = e.getInt("foreground_gray"); paint.color = Color.rgb(g, g, g)
                val desired = e.getDouble("font_glyph_height_px").toFloat() * sx
                paint.textSize = desired; val glyphBounds = Rect(); val text = e.getString("text")
                repeat(3) { paint.getTextBounds(text, 0, text.length, glyphBounds); paint.textSize *= desired / maxOf(1, glyphBounds.height()) }
                paint.getTextBounds(text, 0, text.length, glyphBounds)
                e.put("actual_glyph_height_px", glyphBounds.height()).put("font_text_size_px", paint.textSize).put("typeface", "Android default sans-serif")
                val lines = e.getJSONArray("text_lines"); val inks = JSONArray(); paint.textAlign = Paint.Align.LEFT
                for (line in 0 until lines.length()) {
                    val value = lines.getString(line); val bounds = Rect(); paint.getTextBounds(value, 0, value.length, bounds)
                    val cx = box.centerX(); val cy = box.centerY() + (line - (lines.length() - 1) / 2f) * (desired + 5 * sx)
                    val x = cx - (bounds.left + bounds.right) / 2f; val y = cy - (bounds.top + bounds.bottom) / 2f
                    val ink = RectF(x + bounds.left, y + bounds.top, x + bounds.right, y + bounds.bottom)
                    if (!box.contains(ink)) renderValid = false
                    canvas.drawText(value, x, y, paint); inks.put(JSONArray(listOf(ink.left, ink.top, ink.right, ink.bottom)))
                }
                e.put("ink_bounding_boxes_px", inks)
            }
            actual.put(e)
        }
        if (!submitted) {
            submitted = true
            val generationAtDraw = geometryGeneration
            val location = IntArray(2); getLocationOnScreen(location)
            val state = json("timestamp_ns" to timestamp, "timestamp_kind" to "draw_callback_submission_not_photon_onset",
                "view_size_px" to JSONArray(listOf(width, height)), "view_origin_screen_px" to JSONArray(location.toList()),
                "page_id" to spec.getString("page_id"), "target_element_id" to spec.getString("target_element_id"),
                "elements" to actual, "screenshot_path" to "stimulus.png", "render_valid" to renderValid)
            post {
                if (generationAtDraw != geometryGeneration) return@post
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
        val action = when (event.actionMasked) { MotionEvent.ACTION_DOWN -> "down"; MotionEvent.ACTION_UP -> "up"; MotionEvent.ACTION_CANCEL -> "cancel"; else -> return true }
        val beforeElapsed = SystemClock.elapsedRealtimeNanos()
        val uptimeNs = SystemClock.uptimeMillis() * 1_000_000L
        val afterElapsed = SystemClock.elapsedRealtimeNanos()
        val offset = beforeElapsed + (afterElapsed - beforeElapsed) / 2L - uptimeNs
        val ts = event.eventTime * 1_000_000L + offset
        val hit = boxes.firstOrNull { it.second.contains(event.x, event.y) }?.first
        val correct = hit?.optString("element_id") == writer.stimulus.getString("target_element_id")
        store.touch(json("timestamp_ns" to ts, "raw_uptime_ms" to event.eventTime, "event_clock_offset_ns" to offset,
            "mapping_uncertainty_ns" to (afterElapsed - beforeElapsed) / 2L + 1_000_000L, "action" to action, "x_px" to event.x, "y_px" to event.y,
            "element_id" to hit?.getString("element_id"), "correct_target_hit" to correct))
        if (action == "up" && correct && renderValid && writer.stimulus.getString("task") == "visual_search") onCorrect()
        return true
    }
}
