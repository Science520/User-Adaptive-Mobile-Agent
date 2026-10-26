package org.usercamera.mobilepilot

/** UNKNOWN arrival offsets have unidentifiable capture latency: estimates are never marked validated. */
class CameraClockMapper(val realtime: Boolean) {
    private val warmup = mutableListOf<Long>()
    var offsetNs: Long? = null
        private set
    @Synchronized fun observe(sensorNs: Long, arrivalNs: Long) {
        if (!realtime && offsetNs == null) {
            warmup.add(arrivalNs - sensorNs)
            if (warmup.size >= 10) offsetNs = warmup.minOrNull()
        }
    }
    @Synchronized fun mapped(sensorNs: Long): Long? = if (realtime) sensorNs else offsetNs?.let { sensorNs + it }
    fun status(): String = if (realtime) "shared_clock" else if (offsetNs == null) "unavailable" else "estimated_unvalidated"
    @Synchronized fun arrivalOffsetSpreadNs(): Long? = if (warmup.isEmpty()) null else warmup.maxOrNull()!! - warmup.minOrNull()!!
}
