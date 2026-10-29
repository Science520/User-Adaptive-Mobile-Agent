package org.usercamera.mobilepilot
import org.junit.Test
import org.junit.Assert.assertThrows
class CausalObservationTest {
    @Test fun pastAvailableObservationAccepted() {requireCausalObservation(10,12,15)}
    @Test fun futureCaptureRejected() {assertThrows(IllegalArgumentException::class.java) {requireCausalObservation(20,21,15)}}
    @Test fun lateInferenceRejected() {assertThrows(IllegalArgumentException::class.java) {requireCausalObservation(10,20,15)}}
    @Test fun invalidArrivalRejected() {assertThrows(IllegalArgumentException::class.java) {requireCausalObservation(10,9,15)}}
}
