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
const byte MAC[] PROGMEM = { 0x00, 0x52, 0x16, 0x64, 0xC0, 0x39 };
const int SERVER_PORT = 8888;

// Compact state tracking
enum State : uint8_t {
  STOP,
  RUNNING,
  ERR
};

// Motor and limit switch pin definitions
#define EN_A 2
#define IN1 5
#define IN2 A0
#define DLS_A 3

#define EN_B 7
#define IN3 9
#define IN4 8
#define DLS_B 6

// Compact constants
static const uint16_t MAX_OPEN_A_DURATION = 26500;
static const uint16_t MAX_OPEN_B_DURATION = 27500;
static const uint16_t CLOSE_DURATION_A = 29000;
static const uint16_t CLOSE_DURATION_B = 30000;

// Furnace state enum
enum FurnaceState : uint8_t {
  CLOSED,
  OPEN,
  UNKNOWN
};

// Global system state
State state = STOP;
FurnaceState FurnaceAState = CLOSED;
FurnaceState FurnaceBState = CLOSED;

// Timer management
auto runningTimer = timer.in(1000, []() { return false; });

// Ethernet server setup
EthernetServer server(SERVER_PORT);
EthernetClient client;

// Utility function to end furnace routine
void endFurnaceRoutine() {
  digitalWrite(IN1, HIGH);
  digitalWrite(IN2, HIGH);
  digitalWrite(EN_A, LOW);
  digitalWrite(IN4, HIGH);
  digitalWrite(IN3, HIGH);
  digitalWrite(EN_B, LOW);
}

// Furnace A Open Functions
String openFurnaceA() {
  Serial.print(F("Opening furnace A..."));
  strlcpy(reply, "Opening furnace A...", sizeof(reply));
  digitalWrite(IN1, LOW);
  digitalWrite(IN2, HIGH);
  state = RUNNING;
  digitalWrite(EN_A, HIGH);
  runningTimer = timer.in(MAX_OPEN_A_DURATION, emergencyStopOpeningFurnaceA);
  return reply;
}

void gracefulStopOpeningFurnaceA() {
  timer.cancel(runningTimer);
  state = STOP;
  FurnaceAState = OPEN;
  endFurnaceRoutine();
  Serial.println(F("Furnace A opened gracefully."));
}

void emergencyStopOpeningFurnaceA() {
  state = ERR;
  timer.cancel(runningTimer);
  FurnaceAState = OPEN;
  endFurnaceRoutine();
  
  // Auto closing furnace for safety
  digitalWrite(IN1, HIGH);
  digitalWrite(IN2, LOW);
  digitalWrite(EN_A, HIGH);
  runningTimer = timer.in(CLOSE_DURATION_A, EmergencyCloseFurnaceA);
}

void EmergencyCloseFurnaceA() {
  FurnaceAState = UNKNOWN;
  timer.cancel(runningTimer);
  state = ERR;
  endFurnaceRoutine();
  Serial.println(F("Furnace A emergency closed."));
}

String closeFurnaceA() {
  Serial.print(F("Closing furnace A..."));
  strlcpy(reply, "Closing furnace A...", sizeof(reply));
  state = RUNNING;
  digitalWrite(IN1, HIGH);
  digitalWrite(IN2, LOW);
  digitalWrite(EN_A, HIGH);
  runningTimer = timer.in(CLOSE_DURATION_A, gracefulStopClosingFurnaceA);
  return reply;
}

void gracefulStopClosingFurnaceA() {
  FurnaceAState = CLOSED;
  timer.cancel(runningTimer);
  state = STOP;
  endFurnaceRoutine();
  Serial.println(F("Furnace A closed gracefully."));
}

// Furnace B Open Functions (similar to Furnace A)
String openFurnaceB() {
  Serial.print(F("Opening furnace B..."));
  strlcpy(reply, "Opening furnace B...", sizeof(reply));
  digitalWrite(IN4, HIGH);
  digitalWrite(IN3, LOW);
  digitalWrite(EN_B, HIGH);
  state = RUNNING;
  runningTimer = timer.in(MAX_OPEN_B_DURATION, emergencyStopOpeningFurnaceB);
  return reply;
}

void gracefulStopOpeningFurnaceB() {
  timer.cancel(runningTimer);
  state = STOP;
  FurnaceBState = OPEN;
  endFurnaceRoutine();
  Serial.println(F("Furnace B opened gracefully."));
}

void emergencyStopOpeningFurnaceB() {
  state = ERR;
  timer.cancel(runningTimer);
  FurnaceBState = OPEN;
  endFurnaceRoutine();
  
  // Auto closing furnace for safety
  digitalWrite(IN4, LOW);
  digitalWrite(IN3, HIGH);
  digitalWrite(EN_B, HIGH);
  runningTimer = timer.in(CLOSE_DURATION_B, EmergencyCloseFurnaceB);
}

void EmergencyCloseFurnaceB() {
  FurnaceBState = UNKNOWN;
  timer.cancel(runningTimer);
  state = ERR;
  endFurnaceRoutine();
  Serial.println(F("Furnace B emergency closed."));
}

String closeFurnaceB() {
  Serial.print(F("Closing furnace B..."));
  strlcpy(reply, "Closing furnace B...", sizeof(reply));
  state = RUNNING;
  digitalWrite(IN4, LOW);
  digitalWrite(IN3, HIGH);
  digitalWrite(EN_B, HIGH);
  runningTimer = timer.in(CLOSE_DURATION_B, gracefulStopClosingFurnaceB);
  return reply;
}

void gracefulStopClosingFurnaceB() {
  FurnaceBState = CLOSED;
  timer.cancel(runningTimer);
  state = STOP;
  endFurnaceRoutine();
  Serial.println(F("Furnace B closed gracefully."));
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
  snprintf(tempStr, sizeof(tempStr), "Furnace A: %s; Furnace B: %s;", 
           FurnaceAState == CLOSED ? "Closed" : 
           FurnaceAState == OPEN ? "Open" : "Unknown",
           FurnaceBState == CLOSED ? "Closed" : 
           FurnaceBState == OPEN ? "Open" : "Unknown");
  strlcat(internal_reply, tempStr, sizeof(internal_reply));
  
  return internal_reply;
}

// Limit Switch Check Coroutine
COROUTINE(checkLS_coroutine) {
  COROUTINE_LOOP() {
    COROUTINE_DELAY(30);
    
    if (digitalRead(DLS_A) == HIGH) {
      Serial.println(F("Furnace A is HIGH"));
      if (strcmp(command, "Open A") == 0 && state != ERR) {
        gracefulStopOpeningFurnaceA();
      }
    }
    
    if (digitalRead(DLS_B) == HIGH) {
      Serial.println(F("Furnace B is HIGH"));
      if (strcmp(command, "Open B") == 0 && state != ERR) {
        gracefulStopOpeningFurnaceB();
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
          if (strcmp(clientMsg, "Open A") == 0 && state != ERR && state != RUNNING) {
            if (FurnaceAState == CLOSED) {
              strlcpy(reply, openFurnaceA().c_str(), sizeof(reply));
              strlcpy(command, "Open A", sizeof(command));
              client.print(reply);
            } else if (FurnaceAState == OPEN) {
              strlcpy(reply, checkStatus().c_str(), sizeof(reply));
              client.print(reply);
            }
          }
          else if (strcmp(clientMsg, "Close A") == 0 && state != ERR && state != RUNNING) {
            if (FurnaceAState == OPEN) {
              strlcpy(reply, closeFurnaceA().c_str(), sizeof(reply));
              strlcpy(command, "Close A", sizeof(command));
              client.print(reply);
            } else if (FurnaceAState == CLOSED) {
              strlcpy(reply, checkStatus().c_str(), sizeof(reply));
              client.print(reply);
            }
          }
          // Similar processing for Furnace B commands
          else if (strcmp(clientMsg, "Open B") == 0 && state != ERR && state != RUNNING) {
            if (FurnaceBState == CLOSED) {
              strlcpy(reply, openFurnaceB().c_str(), sizeof(reply));
              strlcpy(command, "Open B", sizeof(command));
              client.print(reply);
            } else if (FurnaceBState == OPEN) {
              strlcpy(reply, checkStatus().c_str(), sizeof(reply));
              client.print(reply);
            }
          }
          else if (strcmp(clientMsg, "Close B") == 0 && state != ERR && state != RUNNING) {
            if (FurnaceBState == OPEN) {
              strlcpy(reply, closeFurnaceB().c_str(), sizeof(reply));
              strlcpy(command, "Close B", sizeof(command));
              client.print(reply);
            } else if (FurnaceBState == CLOSED) {
              strlcpy(reply, checkStatus().c_str(), sizeof(reply));
              client.print(reply);
            }
          }
          else if ((strcmp(clientMsg, "Open A") == 0 || strcmp(clientMsg, "Open B") == 0 || 
                    strcmp(clientMsg, "Close A") == 0 || strcmp(clientMsg, "Close B") == 0) && 
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
  pinMode(EN_A, OUTPUT);
  pinMode(EN_B, OUTPUT);
  pinMode(DLS_A, INPUT_PULLUP);
  pinMode(DLS_B, INPUT_PULLUP);
  pinMode(IN1, OUTPUT);
  pinMode(IN2, OUTPUT);
  pinMode(IN4, OUTPUT);
  pinMode(IN3, OUTPUT);
  
  // Initial motor state
  digitalWrite(IN1, HIGH);
  digitalWrite(IN2, HIGH);
  digitalWrite(EN_A, LOW);
  digitalWrite(IN4, HIGH);
  digitalWrite(IN3, HIGH);
  digitalWrite(EN_B, LOW);
  
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
  
  Serial.println(F("Please write either Open A, Close A, Open B, Close B, or Status."));
}

void loop() {
  timer.tick();
  main_coroutine.runCoroutine();
  checkLS_coroutine.runCoroutine();
}