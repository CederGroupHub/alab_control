#include <AceRoutine.h>
#include <SPI.h>             // Required for Ethernet communication
#include <Ethernet.h>        // Use standard Ethernet library
#include <ArduinoJson.h>
#include <P1AM.h>

// --- System parameters ---
const int stepsPerRevolution = 200; // Steps per full revolution for the motor
const int dirPin = 1;  // Direction pin
const int stepPin = 0; // Step pin
const int enablePin = 2; // Enable pin
int rpm = 10;
float rev = 0.0;
unsigned long time_micros, timePrev_micros; // Use a more descriptive name for microseconds time
// Define the target speed in RPM
float targetRPS = rpm / 60.0;
float stepsPerSecond = targetRPS * stepsPerRevolution;
// Use unsigned long for microseconds, calculate carefully to avoid overflow/precision issues
unsigned long microsecondsPerStep = (unsigned long)(1000000.0 / stepsPerSecond);
unsigned long stepPulseDelayMicroseconds = microsecondsPerStep / 2;
unsigned long totalStepsNeeded = 0;
volatile int steps = 0; // Make steps volatile as it's modified in functions called from loop/coroutines

// --- Communication configuration ---
#define serialwaitingtime 5 //time in seconds to wait for the serial connection to be stablished, or it will be canceled
byte mymac[] = { 0x74, 0x69, 0x30, 0x2F, 0x22, 0x36 }; // MAC address of the device
IPAddress ip(192, 168, 1, 177); // Optional: Define a static IP address as fallback
IPAddress gateway(192, 168, 1, 1); // Optional: Define gateway
IPAddress subnet(255, 255, 255, 0); // Optional: Define subnet mask
EthernetServer server(80);     // Create a server object listening on port 80

// Array of string to list the possible commands
const char* commands[] = {
  "Open Top Gripper",
  "Close Top Gripper",
  "Open Bottom Gripper",
  "Close Bottom Gripper",
  "Rotate Motor CW",
  "Rotate Motor CCW"
};
using namespace ace_routine;

// --- System state management ---
String command = "none"; //command to do an action
enum SystemState {
  RUNNING,
  IDLE,
  ESTOP
};
volatile SystemState systemState = IDLE; // Make state volatile

// --- Valve State Management ---
// Variables to hold the desired state for each valve control pin pair.
// These will be written continuously in the main loop.
// Marked volatile as they are updated in coroutines and read in loop.
volatile int valve1_desiredState = LOW; // Controlled by pins 1 & 9 (Bottom Gripper Close)
volatile int valve2_desiredState = LOW; // Controlled by pins 2 & 10 (Top Gripper Close)
volatile int valve3_desiredState = LOW; // Controlled by pins 3 & 11 (Top Gripper Open)
volatile int valve4_desiredState = LOW; // Controlled by pins 4 & 12 (Bottom Gripper Open)
// --- End Valve State Management ---

// Placeholder for variables used in JSON response but not fully defined in original code
String gripperState = "UNKNOWN"; // You might want to update this based on valve desired states
String shakerState = "UNKNOWN";
// float force_reading = 0.0; // REMOVED

// --- Utility Functions ---
String systemStateToString(SystemState state) {
  switch (state) {
    case RUNNING: return "RUNNING";
    case IDLE: return "IDLE";
    case ESTOP: return "ESTOP";
    default: return "UNKNOWN"; // Handle unexpected states
  }
}

// Placeholder functions (replace with actual implementation if needed)
String gripperStateToString(String state) { return state; }
String shakerStateToString(String state) { return state; }


// Helper function to send HTTP JSON replies using EthernetClient
static void sendHTTPJSONReply(EthernetClient client, int httpStatusCode, const char* communicationStatus, const char* reason) {
  DynamicJsonDocument response(256); // Adjust size if needed
  response["communication_status"] = communicationStatus;
  response["reason"] = reason;
  response["system_status"] = systemStateToString(systemState);
  // Commented out as definitions were not provided in original code
  // response["gripper_status"] = gripperStateToString(gripperState);
  // response["shaker_status"] = shakerStateToString(shakerState);
  // response["force_reading"] = String(force_reading); // REMOVED

  // Send HTTP headers
  if (httpStatusCode == 200) {
    client.println("HTTP/1.1 200 OK");
  } else if (httpStatusCode == 404) {
    client.println("HTTP/1.1 404 Not Found");
  } else {
    // Add other status codes if needed
    client.print("HTTP/1.1 ");
    client.print(httpStatusCode);
    client.println(" "); // Add status text if desired
  }
  client.println("Content-Type: application/json");
  client.println("Connection: close"); // Advise client to close connection
  client.println(); // End of headers

  // Send JSON body
  serializeJson(response, client);
  client.println(); // Extra newline for some clients
}

void resetSystemState() {
  systemState = IDLE;
  command = "none";
  steps = 0; // Reset step count
}

// --- Hardware Control Functions ---
void performStep(bool clockwise) {
  // Set the direction
  digitalWrite(dirPin, clockwise ? HIGH : LOW);
  // Generate one step pulse
  digitalWrite(stepPin, HIGH);
  delayMicroseconds(stepPulseDelayMicroseconds); // Duration of the HIGH phase
  digitalWrite(stepPin, LOW);
  delayMicroseconds(stepPulseDelayMicroseconds); // Duration of the LOW phase
}

// --- Action Trigger Functions (called by handlers) ---
void OpenTopGripperAction() {
  if (systemState == IDLE) { // Only start if IDLE
      systemState = RUNNING;
      command = commands[0];
  }
}

void CloseTopGripperAction() {
  if (systemState == IDLE) {
      systemState = RUNNING;
      command = commands[1];
  }
}

void OpenBottomGripperAction() {
  if (systemState == IDLE) {
      systemState = RUNNING;
      command = commands[2];
  }
}

void CloseBottomGripperAction() {
  if (systemState == IDLE) {
      systemState = RUNNING;
      command = commands[3];
  }
}

// Modified to accept parameters directly
void CWRotationAction(int rpm_temp, float rev_temp) {
  if (systemState == IDLE && rpm_temp > 0 && rev_temp > 0) { // Basic validation
    systemState = RUNNING;
    command = commands[4]; // Use correct index
    rpm = rpm_temp;
    rev = rev_temp;

    // Recalculate motor parameters
    targetRPS = rpm / 60.0;
    stepsPerSecond = targetRPS * stepsPerRevolution;
    microsecondsPerStep = (unsigned long)(1000000.0 / stepsPerSecond);
    stepPulseDelayMicroseconds = microsecondsPerStep / 2;
    if (stepPulseDelayMicroseconds == 0) stepPulseDelayMicroseconds = 1; // Avoid divide by zero or zero delay

    totalStepsNeeded = (unsigned long)(rev * stepsPerRevolution);
    steps = 0; // Reset step count for new move
    time_micros = micros(); // Initialize time tracking
    timePrev_micros = time_micros;

    digitalWrite(enablePin, LOW); // Ensure motor is enabled
    Serial.print("Starting CW Rotation: ");
    Serial.print(rev);
    Serial.print(" rev @ ");
    Serial.print(rpm);
    Serial.println(" RPM");
    Serial.print("Total steps: "); Serial.println(totalStepsNeeded);
    Serial.print("Microseconds per step: "); Serial.println(microsecondsPerStep);

  } else {
     Serial.println("CW Rotation request ignored (not IDLE or invalid params)");
  }
}

// Modified to accept parameters directly
void CCWRotationAction(int rpm_temp, float rev_temp) {
  if (systemState == IDLE && rpm_temp > 0 && rev_temp > 0) { // Basic validation
    systemState = RUNNING;
    command = commands[5]; // Use correct index
    rpm = rpm_temp;
    rev = rev_temp;

    // Recalculate motor parameters
    targetRPS = rpm / 60.0;
    stepsPerSecond = targetRPS * stepsPerRevolution;
    microsecondsPerStep = (unsigned long)(1000000.0 / stepsPerSecond);
    stepPulseDelayMicroseconds = microsecondsPerStep / 2;
     if (stepPulseDelayMicroseconds == 0) stepPulseDelayMicroseconds = 1; // Avoid divide by zero or zero delay


    totalStepsNeeded = (unsigned long)(rev * stepsPerRevolution);
    steps = 0; // Reset step count for new move
    time_micros = micros(); // Initialize time tracking
    timePrev_micros = time_micros;

    digitalWrite(enablePin, LOW); // Ensure motor is enabled
    Serial.print("Starting CCW Rotation: ");
    Serial.print(rev);
    Serial.print(" rev @ ");
    Serial.print(rpm);
    Serial.println(" RPM");
    Serial.print("Total steps: "); Serial.println(totalStepsNeeded);
    Serial.print("Microseconds per step: "); Serial.println(microsecondsPerStep);
  } else {
    Serial.println("CCW Rotation request ignored (not IDLE or invalid params)");
  }
}

void EmergencyStopAction() {
  // E-Stop should be immediate, regardless of current state
  systemState = ESTOP;
  command = "ESTOP"; // Assign a specific command for clarity
  Serial.println("E-Stop Triggered!");
}


// --- Coroutines for Actions ---
COROUTINE(TopGripper) {
  COROUTINE_LOOP() {
    if (systemState == RUNNING && command == commands[0]) {
      // Set desired states instead of calling ValveOpen/Close
      valve3_desiredState = HIGH; // Top Open Valve (Pin 3 & 11)
      valve2_desiredState = LOW;  // Top Close Valve (Pin 2 & 10)
      Serial.println("Top Gripper Opening (Desired State Set)");
      resetSystemState(); // System is now IDLE, but valve states persist
    } else if (systemState == RUNNING && command == commands[1]) {
      // Set desired states instead of calling ValveOpen/Close
      valve2_desiredState = HIGH; // Top Close Valve (Pin 2 & 10)
      valve3_desiredState = LOW;  // Top Open Valve (Pin 3 & 11)
      Serial.println("Top Gripper Closing (Desired State Set)");
      resetSystemState(); // System is now IDLE, but valve states persist
    }
    COROUTINE_DELAY(5); // Small delay to yield control
  }
}

COROUTINE(BottomGripper) {
  COROUTINE_LOOP() {
    if (systemState == RUNNING && command == commands[2]) {
      // Set desired states instead of calling ValveOpen/Close
      valve4_desiredState = HIGH; // Bottom Open Valve (Pin 4 & 12)
      valve1_desiredState = LOW;  // Bottom Close Valve (Pin 1 & 9)
      Serial.println("Bottom Gripper Opening (Desired State Set)");
      resetSystemState(); // System is now IDLE, but valve states persist
    } else if (systemState == RUNNING && command == commands[3]) {
      // Set desired states instead of calling ValveOpen/Close
      valve1_desiredState = HIGH; // Bottom Close Valve (Pin 1 & 9)
      valve4_desiredState = LOW;  // Bottom Open Valve (Pin 4 & 12)
      Serial.println("Bottom Gripper Closing (Desired State Set)");
      resetSystemState(); // System is now IDLE, but valve states persist
    }
    COROUTINE_DELAY(5); // Small delay to yield control
  }
}

COROUTINE(Motor) {
  COROUTINE_LOOP() {
    if (systemState == RUNNING && (command == commands[4] || command == commands[5])) {
        time_micros = micros();
        // Check if enough time has passed *and* if we still need to step
        if ((steps < totalStepsNeeded) && (time_micros - timePrev_micros >= microsecondsPerStep)) {
            timePrev_micros = time_micros; // Update time *before* stepping

            if (command == commands[4]) { // CW
                 performStep(true);
            } else { // CCW
                 performStep(false);
            }
            steps++; // Increment step count
        }

        // Check if the target number of steps has been reached
        if (steps >= totalStepsNeeded) {
            Serial.print("Motor Rotation Finished. Steps taken: "); Serial.println(steps);
            resetSystemState();
        } else {
             COROUTINE_YIELD(); // Yield to allow other tasks
        }
    } else {
        COROUTINE_DELAY(5); // Delay if not running motor
    }
  } // End COROUTINE_LOOP
}


COROUTINE(EStop) {
  COROUTINE_LOOP() {
    if (systemState == ESTOP) {
      // Set all valve desired states to LOW
      valve1_desiredState = LOW;
      valve2_desiredState = LOW;
      valve3_desiredState = LOW;
      valve4_desiredState = LOW;

      // Disable motor driver immediately
      digitalWrite(enablePin, HIGH);
      Serial.println("E-Stop Actions Executed: Valves Desired State LOW, Motor Disabled.");

      // Reset state back to IDLE after E-Stop actions are done
      totalStepsNeeded = 0;
      steps = 0;
      resetSystemState();
      Serial.println("System reset to IDLE after E-Stop.");
    }
    COROUTINE_DELAY(5); // Check periodically
  }
}


// --- Argument Parsing Functions ---
static int getIntArg(String url, const char* key, int defaultValue = -1) {
    int value = defaultValue;
    int qMarkPos = url.indexOf('?');
    if (qMarkPos != -1) {
        String queryString = url.substring(qMarkPos + 1);
        int currentPos = 0;
        while (currentPos < queryString.length()) {
            int nextAmp = queryString.indexOf('&', currentPos);
            if (nextAmp == -1) nextAmp = queryString.length();
            String pair = queryString.substring(currentPos, nextAmp);
            int eqPos = pair.indexOf('=');
            if (eqPos != -1) {
                String currentKey = pair.substring(0, eqPos);
                if (currentKey.equals(key)) {
                    value = pair.substring(eqPos + 1).toInt();
                    break; // Found the key
                }
            }
            currentPos = nextAmp + 1;
        }
    }
    return value;
}

static float getFloatArg(String url, const char* key, float defaultValue = -1.0f) {
    float value = defaultValue;
    int qMarkPos = url.indexOf('?');
     if (qMarkPos != -1) {
        String queryString = url.substring(qMarkPos + 1);
        int currentPos = 0;
        while (currentPos < queryString.length()) {
            int nextAmp = queryString.indexOf('&', currentPos);
            if (nextAmp == -1) nextAmp = queryString.length();
            String pair = queryString.substring(currentPos, nextAmp);
            int eqPos = pair.indexOf('=');
            if (eqPos != -1) {
                String currentKey = pair.substring(0, eqPos);
                 if (currentKey.equals(key)) {
                    value = pair.substring(eqPos + 1).toFloat();
                    break; // Found the key
                }
            }
            currentPos = nextAmp + 1;
        }
    }
    return value;
}


// --- Setup Function ---
void setup() {
  // Initialize serial communication
  Serial.begin(115200);
   unsigned long serialStart = millis();
  while (!Serial && (millis() - serialStart < serialwaitingtime * 1000)) {;}
  Serial.println("\nStarting System...");

  // Wait for P1AM Modules to Sign on
  Serial.print("Initializing P1AM Modules...");
  while (!P1.init()) { Serial.print("."); delay(100); }
  Serial.println(" Done.");

  // Configure motor control pins as outputs
  pinMode(dirPin, OUTPUT);
  pinMode(stepPin, OUTPUT);
  pinMode(enablePin, OUTPUT);

  // Set initial state for motor pins
  digitalWrite(stepPin, LOW);
  digitalWrite(dirPin, LOW);
  digitalWrite(enablePin, HIGH); // Start with motor DISABLED

  // Set initial desired state for valves (LOW = Closed/Off)
  valve1_desiredState = LOW;
  valve2_desiredState = LOW;
  valve3_desiredState = LOW;
  valve4_desiredState = LOW;
  Serial.println("Pins configured, Initial Valve States LOW, Motor Disabled.");

  // Initialize Ethernet connection
  Serial.println("Initializing Ethernet...");
  Ethernet.init(5); // Specify CS pin for Ethernet shield

  if (Ethernet.begin(mymac) == 0) {
    Serial.println("Failed to configure Ethernet using DHCP");
    Serial.println("Attempting static IP configuration...");
    Ethernet.begin(mymac, ip, gateway, gateway, subnet);
     if (Ethernet.linkStatus() == LinkOFF) {
        Serial.println("Ethernet cable is not connected.");
     }
  }

  // Check connection status and print IP address
  if (Ethernet.linkStatus() == LinkON) {
     Serial.print("Ethernet Initialized. IP Address: ");
     Serial.println(Ethernet.localIP());
     server.begin(); // Start listening for clients
     Serial.print("HTTP Server started on port 80");
  } else {
     Serial.println("Ethernet connection failed!");
     while(true); // Halt on failure
  }

  // Set initial system state
  resetSystemState(); // Ensures system starts IDLE
  Serial.println("System setup complete. State: IDLE");
}

// --- Main Loop ---
void loop() {
  // Handle Network Requests
  EthernetClient client = server.available(); // Check for incoming clients
  if (client) {                             // If a new client connects,
    Serial.println("\nNew client connected.");
    String currentLine = ""; // String to hold incoming data from client
    String requestUrl = ""; // To store the first line (request line)
    bool firstLine = true;

    while (client.connected()) { // Loop while the client's connected
      if (client.available()) {  // If there's bytes to read from the client,
        char c = client.read();  // Read a byte
        Serial.write(c);       // Print it out the serial monitor (optional)
        if (c == '\n') {       // If the byte is a newline character
          if (currentLine.length() == 0) { // If the current line is blank, end of request
            Serial.println("Received end of HTTP request.");
            // --- Route the request based on the URL ---
            String path = "";
            int spaceIndex = requestUrl.indexOf(' ');
            if (spaceIndex != -1) {
                int secondSpaceIndex = requestUrl.indexOf(' ', spaceIndex + 1);
                if (secondSpaceIndex != -1) {
                    path = requestUrl.substring(spaceIndex + 1, secondSpaceIndex);
                }
            }
             Serial.print("Request path: "); Serial.println(path);

            if (path.startsWith("/open-top-gripper")) {
              OpenTopGripperAction();
              sendHTTPJSONReply(client, 200, "SUCCESS", "Open Top Gripper command received.");
            } else if (path.startsWith("/close-top-gripper")) {
              CloseTopGripperAction();
              sendHTTPJSONReply(client, 200, "SUCCESS", "Close Top Gripper command received.");
            } else if (path.startsWith("/open-bottom-gripper")) {
              OpenBottomGripperAction();
              sendHTTPJSONReply(client, 200, "SUCCESS", "Open Bottom Gripper command received.");
            } else if (path.startsWith("/close-bottom-gripper")) {
              CloseBottomGripperAction();
              sendHTTPJSONReply(client, 200, "SUCCESS", "Close Bottom Gripper command received.");
            } else if (path.startsWith("/cw-motor")) {
              int rpm_temp = getIntArg(path, "rpm", 10); // Provide default values
              float rev_temp = getFloatArg(path, "rev", 1.0f);
              CWRotationAction(rpm_temp, rev_temp);
              sendHTTPJSONReply(client, 200, "SUCCESS", "CW Motor command received.");
            } else if (path.startsWith("/ccw-motor")) {
              int rpm_temp = getIntArg(path, "rpm", 10);
              float rev_temp = getFloatArg(path, "rev", 1.0f);
              CCWRotationAction(rpm_temp, rev_temp);
              sendHTTPJSONReply(client, 200, "SUCCESS", "CCW Motor command received.");
            } else if (path.startsWith("/estop")) {
              EmergencyStopAction();
              sendHTTPJSONReply(client, 200, "SUCCESS", "Emergency Stop command received.");
            } else if (path.startsWith("/state")) { // RENAMED from /get-state
               sendHTTPJSONReply(client, 200, "SUCCESS", "Current system state queried."); // Message kept same
            }
            else {
              sendHTTPJSONReply(client, 404, "FAILED", "Requested endpoint not found.");
            }
            break; // Exit the while loop after sending the response
          } else { currentLine = ""; } // Clear currentLine for next line
        } else if (c != '\r') { currentLine += c; if(firstLine) { requestUrl += c; } } // Add char to line/URL
        if (c == '\n' && firstLine) { firstLine = false; } // Finished reading the first line (URL)
      } // end if client.available()
    }   // end while client.connected()
    delay(1); // Give client time to receive data
    client.stop(); // Close connection
    Serial.println("Client disconnected.");
  } // end if(client)

  // --- Update Valve Outputs based on desired state (Executed Every Loop) ---
  P1.writeDiscrete(valve1_desiredState, 1, 1);  // Pin 1 (Bottom Close)
  P1.writeDiscrete(valve1_desiredState, 1, 9);  // Pin 1+8
  P1.writeDiscrete(valve2_desiredState, 1, 2);  // Pin 2 (Top Close)
  P1.writeDiscrete(valve2_desiredState, 1, 10); // Pin 2+8
  P1.writeDiscrete(valve3_desiredState, 1, 3);  // Pin 3 (Top Open)
  P1.writeDiscrete(valve3_desiredState, 1, 11); // Pin 3+8
  P1.writeDiscrete(valve4_desiredState, 1, 4);  // Pin 4 (Bottom Open)
  P1.writeDiscrete(valve4_desiredState, 1, 12); // Pin 4+8
  // --- End Valve Update ---

  // Run Coroutines for background tasks
  TopGripper.runCoroutine();
  BottomGripper.runCoroutine();
  Motor.runCoroutine();
  EStop.runCoroutine();

}