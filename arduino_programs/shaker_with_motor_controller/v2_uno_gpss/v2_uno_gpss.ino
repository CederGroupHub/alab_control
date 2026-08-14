#include <Arduino.h>
// System parameters
// Actuator PWM pulse width (microseconds):
//   OPEN  = INITIAL_MAG (1600) -- jaws retracted
//   CLOSE = toward MAG_MIN (1200) -- jaws clamped; steps by MAG_DELTA
#define INITIAL_MAG 1600 // default OPEN height (actuator pulse width, us)
#define MAG_MIN 1200 // fully-closed end of travel
#define MAG_MAX 2000 // hard cap for commanded open height (us)
#define MAG_DELTA 25 // step size for open/close sweeps
// After reaching the open setpoint, keep re-commanding it this many times
// so a flaky actuator connection still gets multiple open pulses (mirrors
// how close repeatedly writes while sweeping).
#define OPEN_HOLD_PULSES 8

// Coroutine framework
#include <AceRoutine.h>
using namespace ace_routine;

// Communication configuration
#include <EtherCard.h>
#include <ArduinoJson.h>
static byte mymac[] = { 0x74, 0x69, 0x30, 0x2F, 0x22, 0x33 }; // MAC address of the device
static byte Ethernet::buffer[400]; // Buffer for Ethernet
BufferFiller bfill; // Buffer for the response
bool ethernetReady = false;
// Array of string to list the possible commands
// Index: 0=open, 1=close, 2=reset  (MUST match gripperOpen/Close/resetSystem)
const char* commands[] = { 
  "open gripper",
  "close gripper",
  "reset system"
};

// Gripper
#include <Servo.h>
#define analogIn A0 //Force sensing resistor
#define output5 9 //PWM for actuator
Servo actuator; //create a servo object for the actuators
bool gripper_detect = false; //flag to detect if the object is in the gripper
int mag = INITIAL_MAG; //commanded actuator position (us)
int openTargetUs = INITIAL_MAG; // OPEN height setpoint for the current open command
int force_reading; //to capture force reading from the force sensing resistor
int openHoldPulses = 0; // remaining open re-commands at openTargetUs
unsigned long gripperTime, gripperTimePrev; //for periodic state checking for the gripper
const long gripperCheckDuration = 400; //time in milliseconds to check the gripper state

// Parse ?us=NNNN from an HTTP request line. Clamps to [MAG_MIN, MAG_MAX].
int parseUsParam(const char* data, int defaultUs) {
  const char* p = strstr(data, "us=");
  if (p == NULL) {
    return defaultUs;
  }
  int v = atoi(p + 3);
  if (v < MAG_MIN) {
    v = MAG_MIN;
  }
  if (v > MAG_MAX) {
    v = MAG_MAX;
  }
  return v;
}
enum GripperState {
  OPEN,
  CLOSE
};
GripperState gripperState = OPEN;
String gripperStateToString(GripperState state);
String gripperStateToString(GripperState state) {
  switch (state) {
    case OPEN:
      return "OPEN";
    case CLOSE:
      return "CLOSE";
    default:
      return "UNKNOWN"; // Handle unexpected states
  }
}

void readForceSensor() {
  force_reading = analogRead(analogIn);
  Serial.print("Analog reading:");
  Serial.println(force_reading);
  // FSR pressed hard enough to count as a grip (used only by CLOSE).
  // With INPUT_PULLUP, pressing the FSR lowers the reading; a higher
  // threshold (150 vs 100) triggers sooner and stops with lighter force.
  if (force_reading < 150) {
    gripper_detect = true;
    Serial.println("detected something");
  }
}

// Reset
unsigned long resetTime, resetTimePrev; //for periodic state checking for the emergency reset
const long resetDuration = 5000; //time in milliseconds to check the emergency reset

// System state management
String command = "none"; //command to do an action
enum SystemState {
  RUNNING,
  IDLE,
  ERROR
};
SystemState systemState = IDLE;
String systemStateToString(SystemState state);
String systemStateToString(SystemState state) {
  switch (state) {
    case RUNNING:
      return "RUNNING";
    case IDLE:
      return "IDLE";
    case ERROR:
      return "ERROR";
    default:
      return "UNKNOWN"; // Handle unexpected states
  }
}

// Default state query functions
static void getState(const char* data, BufferFiller& buf) {
  sendHTTPJSONReply(200, "SUCCESS", "Communication with the device is successful.", buf);
}

static void page_404(const char* data, BufferFiller& buf) {
  sendHTTPJSONReply(404, "FAILED", "Requested endpoint not found.", buf);
}

// State change functions
static void sendHTTPJSONReply(int httpStatusCode, const char* communicationStatus, const char* reason, BufferFiller& buf) {
  DynamicJsonDocument response(256);
  response["communication_status"] = communicationStatus;
  response["reason"] = reason;
  response["system_status"] = systemStateToString(systemState);
  // gripper_status is the last commanded/completed gripper state flag.
  // It is NOT a measured jaw position. Use actuator_us for the commanded
  // servo pulse width, and force_reading for the FSR.
  response["gripper_status"] = gripperStateToString(gripperState);
  response["force_reading"] = String(force_reading);
  response["actuator_us"] = mag;
  response["open_target_us"] = openTargetUs;

  if (httpStatusCode == 200){ 
    buf.emit_p(PSTR(
        "HTTP/1.0 200 OK\r\n"
        "Content-Type: application/json\r\n"
        "\r\n"));
  }
  else if (httpStatusCode == 404) {
    buf.emit_p(PSTR(
        "HTTP/1.0 404 Not Found\r\n"
        "Content-Type: application/json\r\n"
        "\r\n"));
  }
  serializeJson(response, buf);
}

void resetSystemState() {
  systemState = IDLE;
  command = "none";
}

COROUTINE(gripper) {
  COROUTINE_LOOP() {
    COROUTINE_DELAY(30);
    readForceSensor();
    COROUTINE_DELAY(30);
    // OPEN: drive actuator pulse width to openTargetUs (the open "height")
    // and hold it with repeated commands. openTargetUs defaults to INITIAL_MAG
    // (1600) and can be overridden via GET /gripper-open?us=NNNN.
    if (systemState == RUNNING && command == commands[0]) {
      gripperTime = millis();
      if ((gripperTime - gripperTimePrev) > gripperCheckDuration) {
        gripperTimePrev = gripperTime;
        if (mag < openTargetUs) {
          mag = mag + MAG_DELTA;
          if (mag > openTargetUs) {
            mag = openTargetUs;
          }
          Serial.print(F("opening to "));
          Serial.print(openTargetUs);
          Serial.print(F(" us, mag="));
          Serial.println(mag);
          actuator.writeMicroseconds(mag);
        } else if (mag > openTargetUs) {
          // Coming from a wider-than-target command: step down to the height.
          mag = mag - MAG_DELTA;
          if (mag < openTargetUs) {
            mag = openTargetUs;
          }
          Serial.print(F("adjusting open height to "));
          Serial.print(openTargetUs);
          Serial.print(F(" us, mag="));
          Serial.println(mag);
          actuator.writeMicroseconds(mag);
        } else {
          // At open height setpoint: keep pulsing so the servo holds it.
          mag = openTargetUs;
          actuator.writeMicroseconds(mag);
          openHoldPulses--;
          Serial.print(F("open hold at "));
          Serial.print(openTargetUs);
          Serial.print(F(" us, remaining="));
          Serial.println(openHoldPulses);
          if (openHoldPulses <= 0) {
            Serial.println(F("opened to target height."));
            gripper_detect = false;
            gripperState = OPEN;
            resetSystemState();
          }
        }
      }
    }
    // CLOSE: step actuator pulse width DOWN toward MAG_MIN until FSR detects
    // a grip (force < 150) or travel is exhausted (ERROR, empty/no grip).
    else if (systemState == RUNNING && command == commands[1]) {
      gripperTime = millis();
      if ((gripperTime - gripperTimePrev) > gripperCheckDuration) {
        gripperTimePrev = gripperTime;
        if (gripper_detect) {
          Serial.println(F("closed properly"));
          gripperState = CLOSE;
          resetSystemState();
        }
        else if (mag >= MAG_MIN && !gripper_detect) {
          mag = mag - MAG_DELTA;
          actuator.writeMicroseconds(mag);
          readForceSensor();
        }
        else if (mag < MAG_MIN) {
          Serial.println(F("closed to maximum but program failed to detect the object."));
          gripperState = CLOSE;
          systemState = ERROR;
          command = "none"; // stop the close sweep; leave mag at closed end
        }
      }
    }
  }
}

void gripperOpenTo(int targetUs) {
  openTargetUs = targetUs;
  if (openTargetUs < MAG_MIN) {
    openTargetUs = MAG_MIN;
  }
  if (openTargetUs > MAG_MAX) {
    openTargetUs = MAG_MAX;
  }
  Serial.print(F("Opening the gripper to height us="));
  Serial.println(openTargetUs);
  systemState = RUNNING;
  gripperTime = millis();
  gripperTimePrev = gripperTime;
  gripper_detect = false;
  // Always run a sweep + hold to the target height, even if flag says OPEN.
  openHoldPulses = OPEN_HOLD_PULSES;
  command = commands[0];
}

void gripperOpen() {
  gripperOpenTo(INITIAL_MAG);
}

static void gripperOpen(const char* data, BufferFiller& buf) {
  // Optional: GET /gripper-open?us=1600  (open to a specific height)
  int targetUs = parseUsParam(data, INITIAL_MAG);
  gripperOpenTo(targetUs);
  sendHTTPJSONReply(200, "SUCCESS", "Communication with the device is successful.", buf);
}

void gripperClose() {
  Serial.print(F("Close function called: "));
  systemState = RUNNING;
  gripperTime = millis();
  gripperTimePrev = gripperTime;
  gripper_detect = false;
  // Start close from the open end so a previous failed close (mag at MAG_MIN)
  // does not immediately re-trip ERROR without moving.
  mag = INITIAL_MAG;
  actuator.writeMicroseconds(mag);
  command = commands[1];
}

static void gripperClose(const char* data, BufferFiller& buf) {
  gripperClose();
  sendHTTPJSONReply(200, "SUCCESS", "Communication with the device is successful.", buf);
}

COROUTINE(reset) {
  COROUTINE_LOOP() {
    COROUTINE_DELAY(30);
    // commands[2] == "reset system" (was incorrectly commands[-1])
    if (systemState==RUNNING && command==commands[2]) {
      resetTime = millis();
      if ((resetTime - resetTimePrev) > resetDuration) {
        resetTimePrev = resetTime;
        gripperState = OPEN;
        mag = INITIAL_MAG;
        openHoldPulses = 0;
        gripper_detect = false;
        actuator.writeMicroseconds(mag);
        COROUTINE_DELAY(3000);
        // Keep commanding open during the settle window.
        actuator.writeMicroseconds(mag);
        resetSystemState();
      }
    }
  }
}

void resetSystem() {
  Serial.println(F("Resetting the system."));
  systemState = RUNNING;
  resetTime = millis();
  resetTimePrev = resetTime;
  command = commands[2]; // "reset system"
}

static void resetSystem(const char* data, BufferFiller& buf) {
  resetSystem();
  sendHTTPJSONReply(200, "SUCCESS", "Communication with the device is successful.", buf);
}

COROUTINE(handleRemoteRequest) {
  COROUTINE_LOOP() {
    COROUTINE_DELAY(30);
    if (!ethernetReady) {
      continue;
    }
    word len = ether.packetReceive();
    word pos = ether.packetLoop(len);

    if (pos) {
      bfill = ether.tcpOffset();
      char* data = (char *) Ethernet::buffer + pos;

      // receive buf hasn't been clobbered by reply yet
      if (strncmp("GET /state", data, 10) == 0) {
        getState(data, bfill);
      }
      else if (strncmp("GET /gripper-open", data, 17) == 0) {
        gripperOpen(data, bfill);
      }
      else if (strncmp("GET /gripper-set", data, 16) == 0) {
        // Alias: GET /gripper-set?us=1600 -- same as open to a height.
        gripperOpen(data, bfill);
      }
      else if (strncmp("GET /gripper-close", data, 18) == 0) {
        gripperClose(data, bfill);
      }
      else if (strncmp("GET /reset", data, 10) == 0) {
        resetSystem(data, bfill);
      }
      else {
        page_404(data, bfill);
      }
      ether.httpServerReply(bfill.position()); // send web page data
    }
  }
}

// USB serial commands (9600 baud): close / open / reset
COROUTINE(handleSerialRequest) {
  COROUTINE_LOOP() {
    COROUTINE_DELAY(30);
    if (Serial.available() != 0) {
      String text = Serial.readStringUntil('\n');
      text.trim();
      if (text == "close" || text == "close gripper") {
        gripperClose();
        Serial.println(F("close command accepted"));
      } else if (text == "open" || text == "open gripper") {
        gripperOpen();
        Serial.println(F("open command accepted"));
      } else if (text == "reset") {
        resetSystem();
        Serial.println(F("reset command accepted"));
      } else if (text.length() > 0) {
        Serial.print(F("Unknown command: "));
        Serial.println(text);
      }
    }
  }
}

void setup()
{
  Serial.begin(9600);
  Serial.setTimeout(200);
  actuator.attach(output5); // attach the actuator to Arduino pin output5 (PWM)
  pinMode(analogIn, INPUT_PULLUP);
  actuator.writeMicroseconds(mag);
  gripperState = OPEN;
  Serial.println(F("shaker and gripper started."));
  gripperTime = millis();
  gripperTimePrev = millis();
  resetTime = millis();
  resetTimePrev = millis();
  readForceSensor();

  // USB serial close/open must work even if the ENC28J60 is absent.
  // Set ENABLE_ETHERNET to 1 when the EtherCard shield is attached.
#define ENABLE_ETHERNET 0
#if ENABLE_ETHERNET
  if (ether.begin(sizeof Ethernet::buffer, mymac) == 0) {
    Serial.println(F("Failed to access Ethernet controller"));
    ethernetReady = false;
  } else {
    ethernetReady = true;
    Serial.println(F("Ethernet controller found."));
  }
#else
  ethernetReady = false;
  Serial.println(F("Ethernet disabled; USB serial commands active."));
#endif
}

void loop()
{
  handleRemoteRequest.runCoroutine();
  handleSerialRequest.runCoroutine();
  gripper.runCoroutine();
  reset.runCoroutine();
}
