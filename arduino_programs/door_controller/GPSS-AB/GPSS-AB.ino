#include <P1AM.h>
#include <SPI.h>
#include <Ethernet.h>
#include <ArduinoJson.h>

// Motor A ; Furnace A
#define enA 2 // enable motor A
#define in1 3
#define in2 4
#define dlsA 0 // door limit switch for box furnace A

// Motor B ; Furnace B
#define enB 6 // enable motor B
#define in3 11
#define in4 7
#define dlsB 1 // door limit switch for box furnace B

// Network configuration
byte mac[] = {0x00, 0x52, 0x16, 0x64, 0xC0, 0x41}; // CHANGE THIS
// IPAddress serverIP(192, 168, 0, 41); // CHANGE THIS
// IPAddress gateway(192, 168, 0, 1);
int serverPort = 80;

// Initialize the Ethernet server
EthernetServer server(serverPort);

// Timer variables
unsigned long currentMillis = 0;
unsigned long previousMillis = 0;
unsigned long furnaceATimer = 0;
unsigned long furnaceBTimer = 0;
const unsigned long closingTime = 26000;
const unsigned long timeoutProtection = 24000; // Timeout protection from original code

// State machine variables
enum FurnaceState
{
  IDLE,
  OPENING,
  CLOSING,
  ERROR
};

FurnaceState furnaceAState = IDLE;
FurnaceState furnaceBState = IDLE;

// Serial wait variables

void setup()
{
  // Initialize serial communication
  Serial.begin(115200);

  // Wait for P1AM modules to sign on
  // while (!P1.init()) {
  //   Serial.println(F("Waiting for Modules to Sign on"));
  // }

  // Configure watchdog
  // P1.configWD(5000, TOGGLE);
  // P1.startWD();

  // Configure I/O pins
  pinMode(enA, OUTPUT);
  pinMode(enB, OUTPUT);
  pinMode(dlsA, INPUT_PULLUP);
  pinMode(dlsB, INPUT_PULLUP);
  attachInterrupt(digitalPinToInterrupt(dlsA), furnaceInterrupt, FALLING);
  attachInterrupt(digitalPinToInterrupt(dlsB), furnaceInterrupt, FALLING);
  pinMode(in1, OUTPUT);
  pinMode(in2, OUTPUT);
  pinMode(in3, OUTPUT);
  pinMode(in4, OUTPUT);
  pinMode(LED_BUILTIN, OUTPUT);

  // Initialize motors to off state
  digitalWrite(in1, HIGH);
  digitalWrite(in2, HIGH);
  digitalWrite(enA, HIGH);
  digitalWrite(in3, HIGH);
  digitalWrite(in4, HIGH);
  digitalWrite(enB, HIGH);

  Serial.println(F("Serial started. Now starting ethernet"));

  // Start Ethernet connection and server
  Ethernet.begin(mac);
  server.begin();

  Serial.print(F("Ethernet/server started at "));
  Serial.print(Ethernet.localIP());
  Serial.print(F(" : "));
  Serial.print(serverPort);
  Serial.print(F(" and gateway "));
  Serial.print(Ethernet.gatewayIP());
  Serial.println(F(" ."));

  // Check for Ethernet hardware
  if (Ethernet.hardwareStatus() == EthernetNoHardware)
  {
    Serial.println(F("Ethernet shield was not found. The code does nothing from now on."));
    // while (true)
    // {
    //   P1.petWD();
    // }
  }

  // Check Ethernet link status
  checkEthernetLink();
}

void checkEthernetLink() {
  if (Ethernet.linkStatus() == LinkOFF) {
    Serial.println(F("Ethernet link is off"));
  }
}

void endFurnaceRoutine()
{
  digitalWrite(in1, HIGH);
  digitalWrite(in2, HIGH);
  digitalWrite(enA, HIGH);
  digitalWrite(in3, HIGH);
  digitalWrite(in4, HIGH);
  digitalWrite(enB, HIGH);
}

String getFurnaceState(int device)
{
  if (device == 1)
  {
    if (furnaceAState == OPENING) {
      return "Opening";
    } else if (furnaceAState == CLOSING) {
      return "Closing";
    } else if (furnaceAState == ERROR) {
      return "Error";
    } else if (digitalRead(dlsA)) {
      return "Closed";
    } else {
      return "Open";
    }
  }
  else if (device == 2)
  {
    if (furnaceBState == OPENING) {
      return "Opening";
    } else if (furnaceBState == CLOSING) {
      return "Closing";
    } else if (furnaceBState == ERROR) {
      return "Error";
    } else if (digitalRead(dlsB)) {
      return "Closed";
    } else {
      return "Open";
    }
  }
}

bool isSystemIdle() {
  return furnaceAState == IDLE && furnaceBState == IDLE;
}

void getFurnaceStatus(JsonDocument &root) {
  root["furnaceA"] = getFurnaceState(1);
  root["furnaceB"] = getFurnaceState(2);
}


void openFurnaceA(JsonDocument &root)
{
  if (!isSystemIdle()) {
    root["error"] = "System is not idle";
    root["success"] = false;
    return;
  }
  if (!digitalRead(dlsA)) {
    root["error"] = "Furnace A is already open";
    root["success"] = false;
    return;
  }
  digitalWrite(in1, LOW);
  digitalWrite(in2, HIGH);
  digitalWrite(enA, HIGH);
  furnaceAState = OPENING;
  furnaceATimer = currentMillis;
  root["success"] = true;
}

void closeFurnaceA(JsonDocument &root)
{
  if (!isSystemIdle()) {
    root["error"] = "System is not idle";
    root["success"] = false;
    return;
  }
  digitalWrite(in1, HIGH);
  digitalWrite(in2, LOW);
  digitalWrite(enA, HIGH);
  furnaceAState = CLOSING;
  furnaceATimer = currentMillis;
  root["success"] = true;
}

void openFurnaceB(JsonDocument &root)
{
  if (!isSystemIdle()) {
    root["error"] = "System is not idle";
    root["success"] = false;
    return;
  }
  if (!digitalRead(dlsB)) {
    root["error"] = "Furnace B is already open";
    root["success"] = false;
    return;
  }
  digitalWrite(in3, LOW);
  digitalWrite(in4, HIGH);
  digitalWrite(enB, HIGH);
  furnaceBState = OPENING;
  furnaceBTimer = currentMillis;
  root["success"] = true;
}

void closeFurnaceB(JsonDocument &root)
{
  if (!isSystemIdle()) {
    root["error"] = "System is not idle";
    root["success"] = false;
    return;
  }
  digitalWrite(in3, HIGH);
  digitalWrite(in4, LOW);
  digitalWrite(enB, HIGH);
  furnaceBState = CLOSING;
  furnaceBTimer = currentMillis;
  root["success"] = true;
}

void notFound(String &response) {
  response = "HTTP/1.1 404 Not Found\r\n";
  response += "Content-Type: application/json\r\n";
  response += "Connection: close\r\n";
  response += "Content-Length: 0\r\n";
  response += "\r\n";
}

void generateResponse(JsonDocument &jsonDoc, String &response) {
  String jsonString = "";
  serializeJson(jsonDoc, jsonString);
  response = "HTTP/1.1 200 OK\r\n";
  response += "Content-Type: application/json\r\n";
  response += "Connection: close\r\n";
  response += "Content-Length: " + String(jsonString.length()) + "\r\n";
  response += "\r\n";
  response += jsonString;
}

void handleClientMessage(String clientMsg, String &response)
{ 
  // Extract the command from HTTP request
  String command = "";
  if (clientMsg.startsWith("GET /")) {
    command = clientMsg.substring(5); // Skip "GET /"
    int spaceIndex = command.indexOf(' ');
    if (spaceIndex != -1) {
      command = command.substring(0, spaceIndex);
    }
  } else {
    notFound(response);
    return;
  }

  DynamicJsonDocument jsonDoc(256);

  if (command == "open_a")
  {
    Serial.println(F("opening furnace A..."));
    openFurnaceA(jsonDoc);
    generateResponse(jsonDoc, response);
  }
  else if (command == "close_a") 
  {
    Serial.println(F("closing furnace A..."));
    closeFurnaceA(jsonDoc);
    generateResponse(jsonDoc, response);
  }
  else if (command == "open_b")
  {
    Serial.println(F("opening furnace B..."));
    openFurnaceB(jsonDoc);
    generateResponse(jsonDoc, response);
  }
  else if (command == "close_b")
  {
    Serial.println(F("closing furnace B..."));
    closeFurnaceB(jsonDoc);
    generateResponse(jsonDoc, response);
  }
  else if (command == "status")
  {
    getFurnaceStatus(jsonDoc);
    generateResponse(jsonDoc, response);
  }
  else {
    Serial.println(F("Invalid command"));
    notFound(response);
  }
}

void furnaceInterrupt()
{
  // Door is fully open
  if (furnaceAState == OPENING || furnaceBState == OPENING) {
    Serial.println(F(" Furnace A or B opened."));
      endFurnaceRoutine();
      furnaceAState = IDLE;
      furnaceBState = IDLE;
  }
}

void loop()
{
  // Pet the watchdog
  // P1.petWD();

  // Get current time
  currentMillis = millis();

  // Handle furnace A state machine
  if (furnaceAState == OPENING || furnaceAState == CLOSING)
  {
    switch (furnaceAState)
    {
    case OPENING:
      if (currentMillis - furnaceATimer >= timeoutProtection)
      {
        // Timeout protection
        endFurnaceRoutine();
        furnaceAState = ERROR;
        furnaceBState = IDLE;
        Serial.println(F(" STOPPED DUE TO TIME PROTECTION!"));
      }
      break;

    case CLOSING:
      if (currentMillis - furnaceATimer >= closingTime)
      {
        // Closing time elapsed
        endFurnaceRoutine();
        furnaceAState = IDLE;
        furnaceBState = IDLE;
        Serial.println(F(" Furnace A closed."));
      }
      break;

    default:
      break;
    }
  }

  // Handle furnace B state machine
  if (furnaceBState == OPENING || furnaceBState == CLOSING)
  {
    switch (furnaceBState)
    {
    case OPENING:
      if (currentMillis - furnaceBTimer >= timeoutProtection)
      {
        // Timeout protection
        endFurnaceRoutine();
        furnaceAState = IDLE;
        furnaceBState = ERROR;
        Serial.println(F(" STOPPED DUE TO TIME PROTECTION!"));
      }
      break;

    case CLOSING:
      if (currentMillis - furnaceBTimer >= closingTime)
      {
        // Closing time elapsed
        endFurnaceRoutine();
        furnaceAState = IDLE;
        furnaceBState = IDLE;
        Serial.println(F(" Furnace B closed."));
      }
      break;

    default:
      break;
    }
  }

  // Listen for incoming clients
  EthernetClient client = server.available();

  if (client)
  {
    Serial.println(F("Client connected."));
    String clientMsg = "";

    while (client.connected())
    {
//      P1.petWD(); // Pet watchdog while client is connected

      if (client.available())
      {
        char c = client.read();
        clientMsg += c;

        if (c == '\n')
        {
          clientMsg.trim();
          Serial.println("RECEIVED>>" + clientMsg);
          break;
        }
      }
    }
    String responseMsg;
    handleClientMessage(clientMsg, responseMsg);
    client.println(responseMsg);
    Serial.println("SENT>>" + responseMsg);
    client.stop();
    Serial.println(F("Client disconnected."));
  }
}
