#include <Arduino.h>
// System parameters
#define INITIAL_MAG 1600 //initial position of the actuator
#define MAG_MIN 1200 //minimum position of the actuator
#define MAG_DELTA 25 //delta value for the actuator

// Coroutine framework
#include <AceRoutine.h>
using namespace ace_routine;

// Communication configuration
#include <EtherCard.h>
#include <ArduinoJson.h>
#define serialwaitingtime 5 //time in seconds to wait for the serial connection to be stablished, or it will be canceled
static byte mymac[] = { 0x74, 0x69, 0x30, 0x2F, 0x22, 0x31 }; // MAC address of the device
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
#define analogIn 18 //Force sensing resistor
#define output5 9 //PWM for actuator
Servo actuator; //create a servo object for the actuators
bool gripper_detect = false; //flag to detect if the object is in the gripper
int mag = INITIAL_MAG; //position of the actuator
int force_reading; //to capture force reading from the force sensing resistor
unsigned long gripperTime, gripperTimePrev; //for periodic state checking for the gripper
const long gripperCheckDuration = 400; //time in milliseconds to check the gripper state
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
  if (force_reading < 100) {
    gripper_detect = true;
    Serial.println("detected something");
  }
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
        }
      }
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
  Serial.print(F("Close function called: "));
  systemState = RUNNING;
  gripperTime = millis();
  gripperTimePrev = gripperTime;
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

COROUTINE(handleRemoteRequest) {
  COROUTINE_LOOP() {
    COROUTINE_DELAY(30);
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
  }
}

void setup()
{
  Serial.begin(9600);
  //  while (!Serial) ;

  Serial.println(F("Micro turned on."));

  if (ether.begin(sizeof Ethernet::buffer, mymac) == 0)
    Serial.println(F("Failed to access Ethernet controller"));

  ether.dhcpSetup();
  actuator.attach(output5); // attach the actuator to Arduino pin output5 (PWM)
  pinMode(analogIn, INPUT_PULLUP);
  pinMode(output1, OUTPUT);
  pinMode(output2, OUTPUT);
  digitalWrite(output1, LOW);
  digitalWrite(output2, LOW);
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
  handleRemoteRequest.runCoroutine();
  gripper.runCoroutine();
  shaker.runCoroutine();
  reset.runCoroutine();
}
