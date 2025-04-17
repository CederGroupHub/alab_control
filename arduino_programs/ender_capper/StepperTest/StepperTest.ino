#include <P1AM.h>

// System parameters
const int stepsPerRevolution = 200; // Steps per full revolution for the motor
const int dirPin = 1;  // Direction pin
const int stepPin = 0; // Step pin
const int enablePin = 2; // Enable pin

// Define the target speed in RPM
const float targetRPM = 10.0;

// Calculate the required delay between step pulse phases for the target RPM
// Calculation:
// RPS = RPM / 60
// StepsPerSecond = RPS * stepsPerRevolution
// MicrosecondsPerStep = 1,000,000 / StepsPerSecond
// DelayPerPhase = MicrosecondsPerStep / 2
const float targetRPS = targetRPM / 60.0;
const float stepsPerSecond = targetRPS * stepsPerRevolution;
// Use unsigned long for microseconds, calculate carefully to avoid overflow/precision issues
const unsigned long microsecondsPerStep = (unsigned long)(1000000.0 / stepsPerSecond);
const unsigned long stepPulseDelayMicroseconds = microsecondsPerStep / 2;

/**
 * @brief Performs a single step of the motor.
 * @param clockwise If true, sets direction pin HIGH, otherwise LOW.
 * (Actual direction depends on wiring, assumes LOW is Clockwise based on setup).
 * @param pulseDelayUs The delay in microseconds for the HIGH and LOW phase of the step pulse.
 */
void performStep(bool clockwise, unsigned long pulseDelayUs) {
    // Set the direction
    digitalWrite(dirPin, clockwise ? HIGH : LOW);

    // Generate one step pulse
    digitalWrite(stepPin, HIGH);
    delayMicroseconds(pulseDelayUs); // Duration of the HIGH phase
    digitalWrite(stepPin, LOW);
    delayMicroseconds(pulseDelayUs); // Duration of the LOW phase
}

void setup() {
    // Initialize serial communication at 115200 bits per second
    Serial.begin(115200);
    Serial.println("Starting Stepper Motor Control...");

    // Wait for P1AM Modules to Sign on
    while (!P1.init()) {
        ; // Do nothing while waiting
    }
    Serial.println("P1AM Initialized.");

    // Configure motor control pins as outputs
    pinMode(dirPin, OUTPUT);
    pinMode(stepPin, OUTPUT);
    pinMode(enablePin, OUTPUT);

    // Set initial state
    digitalWrite(stepPin, LOW);      // Ensure step pin is low initially
    digitalWrite(dirPin, LOW);       // Set initial direction (e.g., LOW for Clockwise)
    digitalWrite(enablePin, LOW);    // Set LOW to ENABLE the motor driver (HIGH usually disables)

    Serial.print("Target RPM: ");
    Serial.println(targetRPM);
    Serial.print("Calculated Step Pulse Delay (us): ");
    Serial.println(stepPulseDelayMicroseconds);

    // Check if calculated delay is too small (implies very high speed potentially)
    if (stepPulseDelayMicroseconds < 1) {
       Serial.println("Warning: Calculated step delay is very small. Speed might be too high.");
       // Optional: Add handling for minimum possible delay if needed
    }
     if (stepsPerSecond <= 0) {
       Serial.println("Warning: Target speed is zero or negative. Motor will not move.");
       digitalWrite(enablePin, HIGH); // Disable motor if speed is not positive
    }
}

void loop() {
  // Check if the calculated speed is valid (> 0) before attempting to step
  if (stepsPerSecond > 0) {
    // Rotate the stepper motor continuously at the calculated speed
    // We'll rotate clockwise (assuming LOW on dirPin means clockwise as set in setup)
    performStep(false, stepPulseDelayMicroseconds); // false corresponds to LOW on dirPin
  }
  // If stepsPerSecond is not positive, the motor remains idle (and disabled by setup if needed)
}