#include <Arduino.h>
#include <SPI.h>
#include <Ethernet.h>
#include <avr/wdt.h>

// Ethernet configuration
byte mac[] = {0x2C, 0xF7, 0xF1, 0x20, 0x26, 0x4a}; // MAC address
IPAddress ip(192, 168, 1, 39); // Static IP address
EthernetServer server(80); // HTTP server port 80

// Relay pin configuration
const int relayPin = 2;

// State definitions
enum State {
  RUNNING,
  STOPPED
};

State state = STOPPED;
int lastRepeatCount = 0; // Stores the last repeat count
int lastDelayTime = 0;   // Stores the last delay time

// Relay control functions
void start_motor() {
  digitalWrite(relayPin, HIGH); // Activate the relay
  state = RUNNING;
}

void stop_motor() {
  digitalWrite(relayPin, LOW); // Deactivate the relay
  state = STOPPED;
}

void repeat_motor(int repeatCount, int delayTime) {
  state = RUNNING; // Set state to RUNNING
  lastRepeatCount = repeatCount; // Save the last repeat count
  lastDelayTime = delayTime;     // Save the last delay time
  
  for (int i = 0; i < repeatCount; i++) {
    if (state == STOPPED) { // Stop repeating if the state changes to STOPPED
      break;
    }
    digitalWrite(relayPin, HIGH); // Activate the relay
    delay(delayTime); // Set activation time
    digitalWrite(relayPin, LOW); // Deactivate the relay
    delay(200); // Set deactivation time
  }

  state = STOPPED; // Set state to STOPPED after the loop
}

// Function to handle HTTP requests
void handleRequest(EthernetClient client) {
  String request = client.readStringUntil('\r');
  client.flush();

  if (request.startsWith("GET /start")) {
    if (state == RUNNING) {
      client.println("HTTP/1.1 400 Bad Request");
      client.println("Content-Type: application/json");
      client.println();
      client.println("{\"status\":\"error\",\"reason\":\"Motor is already running.\"}");
    } else {
      start_motor();
      client.println("HTTP/1.1 200 OK");
      client.println("Content-Type: application/json");
      client.println();
      client.println("{\"status\":\"success\",\"action\":\"start\"}");
    }
  } else if (request.startsWith("GET /stop")) {
    if (state == STOPPED) {
      client.println("HTTP/1.1 400 Bad Request");
      client.println("Content-Type: application/json");
      client.println();
      client.println("{\"status\":\"error\",\"reason\":\"Motor is already stopped.\"}");
    } else {
      stop_motor();
      client.println("HTTP/1.1 200 OK");
      client.println("Content-Type: application/json");
      client.println();
      client.println("{\"status\":\"success\",\"action\":\"stop\"}");
    }
  } else if (request.startsWith("GET /repeat")) {
    int repeatCount = 1; // Default: 1 time
    int delayTime = 200; // Default: 200ms

    // Parse count and time from the request
    if (request.indexOf("count=") != -1) {
      int startIndex = request.indexOf("count=") + 6;
      int endIndex = request.indexOf('&', startIndex);
      if (endIndex == -1) endIndex = request.length();
      repeatCount = request.substring(startIndex, endIndex).toInt();
    }

    if (request.indexOf("time=") != -1) {
      int startIndex = request.indexOf("time=") + 5;
      int endIndex = request.indexOf('&', startIndex);
      if (endIndex == -1) endIndex = request.length();
      delayTime = request.substring(startIndex, endIndex).toInt();
    }

    // Execute
    if (state == RUNNING) {
      client.println("HTTP/1.1 400 Bad Request");
      client.println("Content-Type: application/json");
      client.println();
      client.println("{\"status\":\"error\",\"reason\":\"Motor is already running.\"}");
    } else {
      repeat_motor(repeatCount, delayTime);
      client.println("HTTP/1.1 200 OK");
      client.println("Content-Type: application/json");
      client.println();
      client.println("{\"status\":\"success\",\"action\":\"repeat\",\"count\":" + String(repeatCount) + ",\"time\":" + String(delayTime) + "}");
    }
  } else if (request.startsWith("GET /state")) {
    client.println("HTTP/1.1 200 OK");
    client.println("Content-Type: application/json");
    client.println();
    client.println("{\"status\":\"success\",\"state\":\"" + String(state == RUNNING ? "RUNNING" : "STOPPED") + "\",\"lastRepeatCount\":" + String(lastRepeatCount) + ",\"lastDelayTime\":" + String(lastDelayTime) + "}");
  } else {
    client.println("HTTP/1.1 404 Not Found");
    client.println("Content-Type: application/json");
    client.println();
    client.println("{\"status\":\"error\",\"reason\":\"Endpoint not found.\"}");
  }
}

void setup() {
  pinMode(relayPin, OUTPUT);
  digitalWrite(relayPin, LOW); // Initial relay OFF
  Serial.begin(9600);

  // Start Ethernet
  if (Ethernet.begin(mac) == 0) {
    Serial.println("Failed to configure Ethernet using DHCP");
    Ethernet.begin(mac, ip); // Manually set IP address
  }
  server.begin(); // Start the server
  Serial.println("Ethernet setup complete");
  Serial.print("Server is at ");
  Serial.println(Ethernet.localIP());
  wdt_enable(WDTO_2S);
}

void loop() {
  wdt_reset();
  EthernetClient client = server.available();
  if (client) {
    Serial.println("New client connected");
    while (client.connected()) {
      if (client.available()) {
        handleRequest(client);
        break;
      }
    }
    client.stop();
    Serial.println("Client disconnected");
  }
}
