#include <Arduino.h>
// System parameters
#define INITIAL_MAG 1600 //initial position of the actuator
#define MAG_MIN 1200 //minimum position of the actuator
#define MAG_DELTA 15 //delta value for the actuator

// Coroutine framework
#include <AceRoutine.h>
using namespace ace_routine;

// Communication configuration
#define USE_ETHERNET 1 // 1 = HTTP on port 80 (AlabOS driver); 0 = USB serial only
#include <EtherCard.h>
#include <ArduinoJson.h>
#define serialwaitingtime 5 //time in seconds to wait for the serial connection to be stablished, or it will be canceled
#define NIP 192, 168, 1, 189
static byte mymac[] = { 0x74, 0x69, 0x30, 0x2F, 0x22, 0x31 }; // MAC address of the device
static byte myip[] = { NIP };
static byte Ethernet::buffer[400]; // Buffer for Ethernet
BufferFiller bfill; // Buffer for the response
// Array of string to list the possible commands
const char* commands[] = { 
  "start shaker",
  "stop shaker",
  "open gripper",
  "close gripper",
  "reset system"
};

// Gripper
#include <Servo.h>
#define analogIn A0 //Force sensing resistor
#define output5 9 //PWM for actuator
#define outputRelay5V 3 // For relay power
#define outputPower 2 // For power cutoff
Servo actuator; //create a servo object for the actuators
bool gripper_detect = false; //flag to detect if the object is in the gripper
int mag = INITIAL_MAG; //position of the actuator
int force_reading; //to capture force reading from the force sensing resistor
int force_baseline = 1023; //FSR reading at start of close (unloaded / free motion)
unsigned long gripperTime, gripperTimePrev; //for periodic state checking for the gripper
unsigned long closeStartTime; //when the current close command began
const long gripperCheckDuration = 500; //time in milliseconds between close steps
// Quasi force-sensing (FSR + pull-up: lower reading => higher force)
#define FORCE_HARD_LIMIT 150 //absolute stop threshold
#define FORCE_DROP_DELTA 40 //stop if reading drops this much from close baseline
#define CLOSE_MAX_MS 25000 //abort close if it takes longer than this
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
  static unsigned long lastPrintMs = 0;
  unsigned long now = millis();
  if ((now - lastPrintMs) >= 5000) {
    lastPrintMs = now;
    Serial.print(F("Analog reading:"));
    Serial.println(force_reading);
  }
}

// Returns true when grip resistance exceeds the tuned limit.
// Uses absolute threshold + rise relative to the free-motion baseline at close start.
bool resistanceTooHigh() {
  if (force_reading < FORCE_HARD_LIMIT) {
    return true;
  }
  if ((force_baseline - force_reading) >= FORCE_DROP_DELTA) {
    return true;
  }
  return false;
}

void holdGripperPosition() {
  actuator.writeMicroseconds(mag);
}

void stopCloseOnResistance(const __FlashStringHelper* reason) {
  holdGripperPosition();
  gripper_detect = true;
  gripperState = CLOSE;
  Serial.println(reason);
  Serial.print(F("holding mag="));
  Serial.println(mag);
  resetSystemState();
}

// Shaker
#define output1 19 //Start
#define output2 20 //Stop
unsigned long shakerTime, shakerTimePrev; //for periodic state checking of the clicker
const long shakerDuration = 5000; //time in milliseconds to check the clicker state
enum ShakerState {
  STARTING,
  STOPPING,
  ON,
  OFF
};
ShakerState shakerState = OFF;
String shakerStateToString(ShakerState state);
String shakerStateToString(ShakerState state) {
  switch (state) {
    case STARTING:
      return "STARTING";
    case STOPPING:
      return "STOPPING";
    case ON:
      return "ON";
    case OFF:
      return "OFF";
    default:
      return "UNKNOWN"; // Handle unexpected states
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
  response["gripper_status"] = gripperStateToString(gripperState);
  response["shaker_status"] = shakerStateToString(shakerState);
  response["force_reading"] = String(force_reading);

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

void shakerStart() {
  Serial.println(F("Clicker starts the shaker"));
  systemState = RUNNING;
  shakerTime = millis();
  shakerTimePrev = shakerTime;
  command = commands[0];
}

static void shakerStart(const char* data, BufferFiller& buf) {
  shakerStart();
  sendHTTPJSONReply(200, "SUCCESS", "Communication with the device is successful.", buf);
}

void shakerStop() {
  Serial.println(F("Machine stops"));
  systemState = RUNNING;
  shakerTime = millis();
  shakerTimePrev = shakerTime;
  command = commands[1];
}

static void shakerStop(const char* data, BufferFiller& buf) {
  shakerStop();
  sendHTTPJSONReply(200, "SUCCESS", "Communication with the device is successful.", buf);
}

COROUTINE(shaker) {
  COROUTINE_LOOP() {
    COROUTINE_DELAY(30);
    if (systemState == RUNNING && command == commands[0]) {
      shakerTime = millis();
      digitalWrite(outputRelay5V,HIGH);
      digitalWrite(outputPower,HIGH);
      digitalWrite(output1, HIGH);
      shakerState=STARTING;
      if ((shakerTime - shakerTimePrev) > shakerDuration) {
        shakerTimePrev = shakerTime;
        digitalWrite(output1, LOW);
        resetSystemState();
        shakerState=ON;
      }
    }
    else if (systemState == RUNNING && command == commands[1]) {
      shakerTime = millis();
      digitalWrite(outputRelay5V,HIGH);
      digitalWrite(outputPower,LOW);
      digitalWrite(output2, HIGH);
      shakerState=STOPPING;
      if ((shakerTime - shakerTimePrev) > shakerDuration) {
        shakerTimePrev = shakerTime;
        digitalWrite(output2, LOW);
        resetSystemState();
        shakerState=OFF;
      }
    }
    else{
      digitalWrite(outputRelay5V, HIGH);
      digitalWrite(outputPower, HIGH);
      digitalWrite(output1, LOW);
      digitalWrite(output2, LOW);
    }
  }
}

COROUTINE(gripper) {
  COROUTINE_LOOP() {
    COROUTINE_DELAY(30);
    readForceSensor();
    COROUTINE_DELAY(30);
    if (systemState == RUNNING && command == commands[2]) {
      Serial.println(F("opening gripper."));
      mag = 1600;
      actuator.writeMicroseconds(mag);
      COROUTINE_DELAY(3000);
      Serial.println(F("opened."));
      gripper_detect = false;
      gripperState = OPEN;
      resetSystemState();
    }
    else if (systemState == RUNNING && command == commands[3]) {
      gripperTime = millis();
      // Timeout: do not keep fighting a jammed/overloaded grip forever
      if ((gripperTime - closeStartTime) > CLOSE_MAX_MS) {
        Serial.println(F("close timed out; stopping retraction."));
        gripperState = CLOSE;
        systemState = ERROR;
        command = "none";
      }
      else if ((gripperTime - gripperTimePrev) > gripperCheckDuration) {
        gripperTimePrev = gripperTime;
        readForceSensor();

        if (resistanceTooHigh()) {
          stopCloseOnResistance(F("resistance limit reached; stopped closing."));
        }
        else if (mag >= MAG_MIN) {
          // One small retract step; next cycle re-checks after settle time
          mag = mag - MAG_DELTA;
          actuator.writeMicroseconds(mag);
          Serial.print(F("close step mag="));
          Serial.println(mag);
        }
        else {
          Serial.println(F("closed to maximum but program failed to detect the object."));
          gripperState = CLOSE;
          systemState = ERROR;
          command = "none";
        }
      }
    }
    else if (gripperState == CLOSE) {
      holdGripperPosition();
    }
  }
}

void gripperOpen() {
  Serial.println("Opening the gripper");
  systemState = RUNNING;
  gripperTime = millis();
  gripperTimePrev = gripperTime;
  command = commands[2];
}

static void gripperOpen(const char* data, BufferFiller& buf) {
  gripperOpen();
  sendHTTPJSONReply(200, "SUCCESS", "Communication with the device is successful.", buf);
}

void gripperClose() {
  Serial.println(F("Close function called"));
  systemState = RUNNING;
  gripper_detect = false;
  gripperTime = millis();
  gripperTimePrev = gripperTime;
  closeStartTime = gripperTime;
  // Capture unloaded baseline so relative force rise can stop the close early
  readForceSensor();
  force_baseline = force_reading;
  Serial.print(F("Close force baseline: "));
  Serial.println(force_baseline);
  command = commands[3];
}

static void gripperClose(const char* data, BufferFiller& buf) {
  gripperClose();
  sendHTTPJSONReply(200, "SUCCESS", "Communication with the device is successful.", buf);
}

COROUTINE(reset) {
  COROUTINE_LOOP() {
    COROUTINE_DELAY(30);
    if (systemState==RUNNING && command==commands[-1]) {
      resetTime = millis();
      digitalWrite(output2, HIGH);
      if ((resetTime - resetTimePrev) > resetDuration) {
        resetTimePrev = resetTime;
        digitalWrite(output2, LOW);
        gripperState = OPEN;
        mag = INITIAL_MAG;
        actuator.writeMicroseconds(mag);
        COROUTINE_DELAY(3000);
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
  command = commands[-1];
}

static void resetSystem(const char* data, BufferFiller& buf) {
  resetSystem();
  sendHTTPJSONReply(200, "SUCCESS", "Communication with the device is successful.", buf);
}

void applySerialCommand(char* line) {
  for (char* p = line; *p; p++) {
    if (*p >= 'A' && *p <= 'Z') {
      *p = *p - 'A' + 'a';
    }
  }
  if (strcmp(line, "open") == 0) {
    gripperOpen();
  } else if (strcmp(line, "close") == 0) {
    gripperClose();
  } else if (strcmp(line, "start") == 0) {
    shakerStart();
  } else if (strcmp(line, "stop") == 0) {
    shakerStop();
  } else if (strcmp(line, "reset") == 0) {
    resetSystem();
  } else if (strcmp(line, "state") == 0) {
    Serial.print(F("system="));
    Serial.print(systemStateToString(systemState));
    Serial.print(F(" gripper="));
    Serial.print(gripperStateToString(gripperState));
    Serial.print(F(" shaker="));
    Serial.print(shakerStateToString(shakerState));
    Serial.print(F(" force="));
    Serial.println(force_reading);
  } else if (line[0] != '\0') {
    Serial.println(F("commands: open, close, start, stop, reset, state"));
  }
}

COROUTINE(handleSerialCommand) {
  COROUTINE_LOOP() {
    COROUTINE_DELAY(30);
    static char buf[32];
    static uint8_t idx = 0;
    while (Serial.available()) {
      char c = Serial.read();
      if (c == '\r') {
        continue;
      }
      if (c == '\n') {
        buf[idx] = '\0';
        idx = 0;
        applySerialCommand(buf);
      } else if (idx < sizeof(buf) - 1) {
        buf[idx++] = c;
      }
    }
  }
}

COROUTINE(handleRemoteRequest) {
  COROUTINE_LOOP() {
    COROUTINE_DELAY(30);
#if USE_ETHERNET
    word len = ether.packetReceive();
    word pos = ether.packetLoop(len);

    if (pos) {
      bfill = ether.tcpOffset();
      char* data = (char *) Ethernet::buffer + pos;

      // receive buf hasn't been clobbered by reply yet
      if (strncmp("GET /start", data, 10) == 0) {
        shakerStart(data, bfill);
      }
      else if (strncmp("GET /stop", data, 9) == 0) {
        shakerStop(data, bfill);
      }
      else if (strncmp("GET /state", data, 10) == 0) {
        getState(data, bfill);
      }
      else if (strncmp("GET /gripper-open", data, 17) == 0) {
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
#endif
  }
}

void setup()
{
  Serial.begin(9600);
  //  while (!Serial) ;

  Serial.println(F("Micro turned on."));
  Serial.println(F("USB commands: open, close, start, stop, reset, state"));

#if USE_ETHERNET
  if (ether.begin(sizeof Ethernet::buffer, mymac) == 0)
    Serial.println(F("Failed to access Ethernet controller"));
  else {
    ether.staticSetup(myip);
    Serial.print(F("IP was set to: "));
    for (int i = 0; i < 4; i++) {
      Serial.print(String(myip[i]));
      if (i < 3) {
        Serial.print(".");
      } else {
        Serial.println("");
      }
    }
    Serial.println(F("HTTP: GET /start /stop /state /gripper-open /gripper-close /reset"));
  }
#else
  Serial.println(F("Ethernet disabled; using USB serial."));
#endif
  actuator.attach(output5); // attach the actuator to Arduino pin output5 (PWM)
  pinMode(analogIn, INPUT_PULLUP);
  pinMode(output1, OUTPUT);
  pinMode(output2, OUTPUT);
  digitalWrite(output1, LOW);
  digitalWrite(output2, LOW);
  pinMode(outputRelay5V, OUTPUT);
  pinMode(outputPower, OUTPUT);
  digitalWrite(outputPower,HIGH);
  shakerStop();
  actuator.writeMicroseconds(mag);
  gripperState = OPEN;
  Serial.println(F("shaker and gripper started."));
  gripperTime = millis();
  gripperTimePrev = millis();
  shakerTime = millis();
  shakerTimePrev = millis();
  resetTime = millis();
  resetTimePrev = millis();
  readForceSensor();
}

void loop()
{
  digitalWrite(outputRelay5V,HIGH);
  handleSerialCommand.runCoroutine();
  handleRemoteRequest.runCoroutine();
  gripper.runCoroutine();
  shaker.runCoroutine();
  reset.runCoroutine();
}