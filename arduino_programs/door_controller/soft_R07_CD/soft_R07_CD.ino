#include <SPI.h>
#include <Ethernet.h>
#include <arduino-timer.h>
#include <AceRoutine.h>

Timer<3> timer;

// Minimize global string allocations
char clientMsg[32] = {0}; // Fixed-size char array instead of String
char reply[128] = {0};
char internal_reply[128] = {0};
char command[16] = {0};

// Use const for constant values to store in program memory
const byte MAC[] PROGMEM = { 0x00, 0x52, 0x16, 0x64, 0xC0, 0x11 };
const int SERVER_PORT = 8888;

// Compact state tracking
enum State : uint8_t {
  STOP,
  RUNNING,
  ERR
};

// Motor and limit switch pin definitions
#define EN_C 2
#define IN1 A0
#define IN2 3
#define DLS_C 5

#define EN_D 6
#define IN3 8
#define IN4 7
#define DLS_D 9

// Compact constants
static const uint16_t MAX_OPEN_C_DURATION = 21000;
static const uint16_t MAX_OPEN_D_DURATION = 21000;
static const uint16_t CLOSE_DURATION_C = 25000;
static const uint16_t CLOSE_DURATION_D = 25000;

// Furnace state enum
enum FurnaceState : uint8_t {
  CLOSED,
  OPEN,
  UNKNOWN
};

// Global system state
State state = STOP;
FurnaceState FurnaceCState = CLOSED;
FurnaceState FurnaceDState = CLOSED;

// Timer management
auto runningTimer = timer.in(1000, []() { return false; });

// Ethernet server setup
EthernetServer server(SERVER_PORT);
EthernetClient client;

// Utility function to end furnace routine
void endFurnaceRoutine() {
  digitalWrite(IN1, HIGH);
  digitalWrite(IN2, HIGH);
  digitalWrite(EN_C, LOW);
  digitalWrite(IN4, HIGH);
  digitalWrite(IN3, HIGH);
  digitalWrite(EN_D, LOW);
}

// Furnace C Open Functions
String openFurnaceC() {
  Serial.print(F("Opening furnace C..."));
  strlcpy(reply, "Opening furnace C...", sizeof(reply));
  digitalWrite(IN1, LOW);
  digitalWrite(IN2, HIGH);
  state = RUNNING;
  digitalWrite(EN_C, HIGH);
  runningTimer = timer.in(MAX_OPEN_C_DURATION, emergencyStopOpeningFurnaceC);
  return reply;
}

void gracefulStopOpeningFurnaceC() {
  timer.cancel(runningTimer);
  state = STOP;
  FurnaceCState = OPEN;
  endFurnaceRoutine();
  Serial.println(F("Furnace C opened gracefully."));
}

void emergencyStopOpeningFurnaceC() {
  state = ERR;
  timer.cancel(runningTimer);
  FurnaceCState = OPEN;
  endFurnaceRoutine();
  
  // Auto closing furnace for safety
  digitalWrite(IN1, HIGH);
  digitalWrite(IN2, LOW);
  digitalWrite(EN_C, HIGH);
  runningTimer = timer.in(CLOSE_DURATION_C, EmergencyCloseFurnaceC);
}

void EmergencyCloseFurnaceC() {
  FurnaceCState = UNKNOWN;
  timer.cancel(runningTimer);
  state = ERR;
  endFurnaceRoutine();
  Serial.println(F("Furnace C emergency closed."));
}

String closeFurnaceC() {
  Serial.print(F("Closing furnace C..."));
  strlcpy(reply, "Closing furnace C...", sizeof(reply));
  state = RUNNING;
  digitalWrite(IN1, HIGH);
  digitalWrite(IN2, LOW);
  digitalWrite(EN_C, HIGH);
  runningTimer = timer.in(CLOSE_DURATION_C, gracefulStopClosingFurnaceC);
  return reply;
}

void gracefulStopClosingFurnaceC() {
  FurnaceCState = CLOSED;
  timer.cancel(runningTimer);
  state = STOP;
  endFurnaceRoutine();
  Serial.println(F("Furnace C closed gracefully."));
}

// Furnace D Open Functions
String openFurnaceD() {
  Serial.print(F("Opening furnace D..."));
  strlcpy(reply, "Opening furnace D...", sizeof(reply));
  digitalWrite(IN4, HIGH);
  digitalWrite(IN3, LOW);
  digitalWrite(EN_D, HIGH);
  state = RUNNING;
  runningTimer = timer.in(MAX_OPEN_D_DURATION, emergencyStopOpeningFurnaceD);
  return reply;
}

void gracefulStopOpeningFurnaceD() {
  timer.cancel(runningTimer);
  state = STOP;
  FurnaceDState = OPEN;
  endFurnaceRoutine();
  Serial.println(F("Furnace D opened gracefully."));
}

void emergencyStopOpeningFurnaceD() {
  state = ERR;
  timer.cancel(runningTimer);
  FurnaceDState = OPEN;
  endFurnaceRoutine();
  
  // Auto closing furnace for safety
  digitalWrite(IN4, LOW);
  digitalWrite(IN3, HIGH);
  digitalWrite(EN_D, HIGH);
  runningTimer = timer.in(CLOSE_DURATION_D, EmergencyCloseFurnaceD);
}

void EmergencyCloseFurnaceD() {
  FurnaceDState = UNKNOWN;
  timer.cancel(runningTimer);
  state = ERR;
  endFurnaceRoutine();
  Serial.println(F("Furnace D emergency closed."));
}

String closeFurnaceD() {
  Serial.print(F("Closing furnace D..."));
  strlcpy(reply, "Closing furnace D...", sizeof(reply));
  state = RUNNING;
  digitalWrite(IN4, LOW);
  digitalWrite(IN3, HIGH);
  digitalWrite(EN_D, HIGH);
  runningTimer = timer.in(CLOSE_DURATION_D, gracefulStopClosingFurnaceD);
  return reply;
}

void gracefulStopClosingFurnaceD() {
  FurnaceDState = CLOSED;
  timer.cancel(runningTimer);
  state = STOP;
  endFurnaceRoutine();
  Serial.println(F("Furnace D closed gracefully."));
}

// Status Check Function
String checkStatus() {
  internal_reply[0] = '\0'; // Clear previous content
  strlcpy(internal_reply, "State: ", sizeof(internal_reply));
  
  // Append state information
  if (state == ERR) {
    strlcat(internal_reply, "ERROR; ", sizeof(internal_reply));
  } else if (state == RUNNING) {
    strlcat(internal_reply, "RUNNING; ", sizeof(internal_reply));
  } else if (state == STOP) {
    strlcat(internal_reply, "STOP; ", sizeof(internal_reply));
  }
  
  // Append furnace states
  char tempStr[64];
  snprintf(tempStr, sizeof(tempStr), "Furnace C: %s; Furnace D: %s;", 
           FurnaceCState == CLOSED ? "Closed" : 
           FurnaceCState == OPEN ? "Open" : "Unknown",
           FurnaceDState == CLOSED ? "Closed" : 
           FurnaceDState == OPEN ? "Open" : "Unknown");
  strlcat(internal_reply, tempStr, sizeof(internal_reply));
  
  return internal_reply;
}

// Limit Switch Check Coroutine
COROUTINE(checkLS_coroutine) {
  COROUTINE_LOOP() {
    COROUTINE_DELAY(30);
    
    if (digitalRead(DLS_C) == HIGH) {
      Serial.println(F("Furnace C is HIGH"));
      if (strcmp(command, "Open C") == 0 && state != ERR) {
        gracefulStopOpeningFurnaceC();
      }
    }
    
    if (digitalRead(DLS_D) == HIGH) {
      Serial.println(F("Furnace D is HIGH"));
      if (strcmp(command, "Open D") == 0 && state != ERR) {
        gracefulStopOpeningFurnaceD();
      }
    }
  }
}

// Main Communication Coroutine
COROUTINE(main_coroutine) {
  COROUTINE_LOOP() {
    COROUTINE_DELAY(30);
    
    // Listen for incoming clients
    EthernetClient client = server.available();
    if (client) {
      Serial.println(F("Client connected."));
      
      while (client.connected()) {
        if (client.available()) {
          // Clear previous message
          clientMsg[0] = '\0';
          
          // Read incoming message
          int idx = 0;
          while (client.available() && idx < sizeof(clientMsg) - 1) {
            char c = client.read();
            if (c == '\n') break;
            clientMsg[idx++] = c;
          }
          clientMsg[idx] = '\0';
          
          Serial.print(F("RECEIVED>> ")); 
          Serial.println(clientMsg);
          
          // Command processing
          if (strcmp(clientMsg, "Open C") == 0 && state != ERR && state != RUNNING) {
            if (FurnaceCState == CLOSED) {
              strlcpy(reply, openFurnaceC().c_str(), sizeof(reply));
              strlcpy(command, "Open C", sizeof(command));
              client.print(reply);
            } else if (FurnaceCState == OPEN) {
              strlcpy(reply, checkStatus().c_str(), sizeof(reply));
              client.print(reply);
            }
          }
          else if (strcmp(clientMsg, "Close C") == 0 && state != ERR && state != RUNNING) {
            if (FurnaceCState == OPEN) {
              strlcpy(reply, closeFurnaceC().c_str(), sizeof(reply));
              strlcpy(command, "Close C", sizeof(command));
              client.print(reply);
            } else if (FurnaceCState == CLOSED) {
              strlcpy(reply, checkStatus().c_str(), sizeof(reply));
              client.print(reply);
            }
          }
          else if (strcmp(clientMsg, "Open D") == 0 && state != ERR && state != RUNNING) {
            if (FurnaceDState == CLOSED) {
              strlcpy(reply, openFurnaceD().c_str(), sizeof(reply));
              strlcpy(command, "Open D", sizeof(command));
              client.print(reply);
            } else if (FurnaceDState == OPEN) {
              strlcpy(reply, checkStatus().c_str(), sizeof(reply));
              client.print(reply);
            }
          }
          else if (strcmp(clientMsg, "Close D") == 0 && state != ERR && state != RUNNING) {
            if (FurnaceDState == OPEN) {
              strlcpy(reply, closeFurnaceD().c_str(), sizeof(reply));
              strlcpy(command, "Close D", sizeof(command));
              client.print(reply);
            } else if (FurnaceDState == CLOSED) {
              strlcpy(reply, checkStatus().c_str(), sizeof(reply));
              client.print(reply);
            }
          }
          else if ((strcmp(clientMsg, "Open C") == 0 || strcmp(clientMsg, "Open D") == 0 || 
                    strcmp(clientMsg, "Close C") == 0 || strcmp(clientMsg, "Close D") == 0) && 
                   (state == ERR || state == RUNNING)) {
            strlcpy(reply, checkStatus().c_str(), sizeof(reply));
            client.print(reply);
          }
          else if (strcmp(clientMsg, "Status") == 0) {
            strlcpy(reply, checkStatus().c_str(), sizeof(reply));
            client.print(reply);
          }
          else {
            Serial.println(F("Wrong command"));
            client.print(F("Wrong command"));
          }
        }
      }
      
      // Give the client time to receive data
      delay(10);
      
      // Close the connection
      client.stop();
      Serial.println(F("Client disconnected."));
    }
  }
}

void setup() {
  timer.cancel(runningTimer);
  Serial.end(); // Restart serial communication
  Serial.begin(9600);
  
  // Configure pins
  pinMode(EN_C, OUTPUT);
  pinMode(EN_D, OUTPUT);
  pinMode(DLS_C, INPUT_PULLUP);
  pinMode(DLS_D, INPUT_PULLUP);
  pinMode(IN1, OUTPUT);
  pinMode(IN2, OUTPUT);
  pinMode(IN4, OUTPUT);
  pinMode(IN3, OUTPUT);
  
  // Initial motor state
  digitalWrite(IN1, HIGH);
  digitalWrite(IN2, HIGH);
  digitalWrite(EN_C, LOW);
  digitalWrite(IN4, HIGH);
  digitalWrite(IN3, HIGH);
  digitalWrite(EN_D, LOW);
  
  // Serial initialization with timeout
  uint8_t serialwait = 0;
  const uint8_t serialwaitingtime = 6;
  
  while (!Serial) {
    delay(1000);
    if (serialwait == serialwaitingtime) {
      break;
    }
    serialwait++;
  }
  
  Serial.println(F("Serial started. Now starting ethernet"));
  
  // Ethernet initialization
  byte mac[6];
  memcpy_P(mac, MAC, sizeof(mac));
  
  if (Ethernet.begin(mac) == 0) {
    Serial.println(F("Failed to configure Ethernet using DHCP"));
    while (true) {
      delay(1000);
    }
  }
  
  server.begin();
  Serial.print(F("Ethernet/server started at "));
  Serial.print(Ethernet.localIP());
  Serial.print(F(" : "));
  Serial.print(SERVER_PORT);
  Serial.print(F(" and gateway "));
  Serial.print(Ethernet.gatewayIP());
  Serial.println(F(" ."));
  
  // Check Ethernet hardware
  if (Ethernet.hardwareStatus() == EthernetNoHardware) {
    Serial.println(F("Ethernet shield was not found."));
    while (true) {
      delay(1000);
    }
  }
  
  // Check Ethernet connection
  if (Ethernet.linkStatus() == LinkOFF) {
    while (Ethernet.linkStatus() == LinkOFF) {
      Serial.println(F("Ethernet cable is not connected. Trying again in 2 seconds."));
      delay(2000);
    }
    Serial.println(F("Ethernet cable is now detected. Resuming the routine now..."));
  }
  
  Serial.println(F("Please write either Open C, Close C, Open D, Close D, or Status."));
}

void loop() {
  timer.tick();
  main_coroutine.runCoroutine();
  checkLS_coroutine.runCoroutine();
}