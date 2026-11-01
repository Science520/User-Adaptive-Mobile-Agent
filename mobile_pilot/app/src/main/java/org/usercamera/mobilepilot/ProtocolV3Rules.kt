package org.usercamera.mobilepilot

fun isInteractionTask(task: String): Boolean = task in setOf("readability","visual_search","mixed")
fun interventionSource(mode: String): String = when(mode) {
    "requested_only" -> "self_selected"
    "assigned_pre_task" -> "rescue_crossover"
    else -> throw IllegalArgumentException("Unknown research mode")
}
fun assistanceEffect(action: String): String = when(action) {
    "zoom_text" -> "zoom"
    "increase_contrast" -> "contrast"
    "highlight_target" -> "highlight"
    else -> action
}

fun taskLabel(task: String): String = when(task) {
    "readability" -> "R 文字辨认"
    "visual_search" -> "S 服务查找"
    "mixed" -> "M 组合负荷"
    else -> "注视"
}
fun helpfulnessAnswerValid(deliveredHelp: Boolean, answer: Int): Boolean = !deliveredHelp || answer in 1..5 || answer == -1
