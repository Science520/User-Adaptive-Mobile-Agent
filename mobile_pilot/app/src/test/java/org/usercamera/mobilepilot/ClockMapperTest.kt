package org.usercamera.mobilepilot
import org.junit.Assert.*
import org.junit.Test

class ClockMapperTest {
    @Test fun realtimeIsIdentity() {
        val m = CameraClockMapper(true); m.observe(100, 150)
        assertEquals(100L, m.mapped(100)); assertEquals("shared_clock", m.status())
    }
    @Test fun unknownNeverClaimsValidatedSynchronization() {
        val m = CameraClockMapper(false)
        assertNull(m.mapped(100))
        repeat(10) { m.observe(it * 100L, it * 100L + 500L + it) }
        assertEquals("estimated_unvalidated", m.status()); assertEquals(600L, m.mapped(100))
    }
}
