plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
    id("org.jetbrains.kotlin.plugin.compose")
}
android {
    namespace = "org.usercamera.mobilepilot"
    compileSdk = 35
    defaultConfig {
        applicationId = "org.usercamera.mobilepilot"
        minSdk = 26
        targetSdk = 35
        versionCode = 2
        versionName = "0.3.0-video-pilot"
        testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner"
    }
    buildFeatures { compose = true }
    compileOptions { sourceCompatibility = JavaVersion.VERSION_17; targetCompatibility = JavaVersion.VERSION_17 }
    kotlinOptions { jvmTarget = "17" }
    buildTypes { release { isMinifyEnabled = false } }
    testOptions { unitTests.isReturnDefaultValues = true }
}
dependencies {
    implementation(platform("androidx.compose:compose-bom:2024.12.01"))
    implementation("androidx.activity:activity-compose:1.9.3")
    implementation("androidx.compose.ui:ui")
    implementation("androidx.compose.foundation:foundation")
    implementation("androidx.compose.material3:material3")
    implementation("androidx.lifecycle:lifecycle-runtime-ktx:2.8.7")
    implementation("androidx.camera:camera-video:1.4.1")
    implementation("androidx.camera:camera-view:1.4.1")
    implementation("com.google.mediapipe:tasks-vision:0.10.21")
    implementation("androidx.camera:camera-core:1.4.1")
    implementation("androidx.camera:camera-camera2:1.4.1")
    implementation("androidx.camera:camera-lifecycle:1.4.1")
    implementation("androidx.core:core-ktx:1.15.0")
    testImplementation("junit:junit:4.13.2")
}
