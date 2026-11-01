package org.usercamera.mobilepilot
import org.junit.Test
import org.junit.Assert.*
class ProtocolV3RulesTest {
    @Test fun allThreeFamiliesAreInteractive() { for(t in listOf("readability","visual_search","mixed")) assertTrue(isInteractionTask(t)) }
    @Test fun fixationAndUnknownAreExcluded() {assertFalse(isInteractionTask("fixation"));assertFalse(isInteractionTask("unknown"))}
    @Test fun selfSelectionIsNotRandomAssignment() {assertEquals("self_selected",interventionSource("requested_only"))}
    @Test fun assignedModeRescueIsCrossover() {assertEquals("rescue_crossover",interventionSource("assigned_pre_task"))}
    @Test fun invalidModeRejected() {assertThrows(IllegalArgumentException::class.java) {interventionSource("mixed_unspecified")}}
    @Test fun targetAndRegionStayDistinct() {assertEquals("highlight",assistanceEffect("highlight_target"));assertEquals("highlight_region",assistanceEffect("highlight_region"))}
    @Test fun readabilityActionsPreserveMeaning() {assertEquals("zoom",assistanceEffect("zoom_text"));assertEquals("contrast",assistanceEffect("increase_contrast"))}
    @Test fun deliveredHelpRequiresActiveAnswer() {assertFalse(helpfulnessAnswerValid(true,0));assertTrue(helpfulnessAnswerValid(true,3));assertTrue(helpfulnessAnswerValid(true,-1))}
    @Test fun noDeliveredHelpDoesNotRequireFakeScore() {assertTrue(helpfulnessAnswerValid(false,0))}
}
