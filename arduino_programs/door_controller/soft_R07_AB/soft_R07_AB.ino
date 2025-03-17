#include <SPI.h>
#include <Ethernet.h>
#include<ArduinoJson.h>
#include <arduino-timer.h>
#include <AceRoutine.h>

Timer<3> timer;

String clientMsg = "";
//String reason = "";
String command = "";
String reply="";
int lsA=0;
int lsB=0;

int serialwait = 0;
int serialwaitingtime = 6;
byte mac[] = { 0x00, 0x52, 0x16, 0x64, 0xC0, 0x39 };
//00:52:16:64:C0:39

int serverPort = 8888;

// Initialize the Ethernet server library
// with the IP address and port you want to use
EthernetServer server(serverPort);
EthernetClient client;

// Furnace closing time
#define serialwaitingtime 5 //time in seconds to wait for the serial connection to be stablished, or it will be canceled.

// Motor A ; Furnace A

#define enA 2 //enable motor A
#define in2 A0
#define in1 5
#define dlsA 3 //door limit switch for box furnace A

// Motor B ; Furnace B

#define enB 7 //enable motor B
#define in4 8
#define in3 9
#define dlsB 6 //door limit switch for box furnace B

//pins 4, 10, 11, 12, 13 are reserved for the ethernet shield

unsigned long currentTime,previousTime,duration;
const long maxOpeningADuration = 26500; // Calibrated 11/21/22
const long maxOpeningBDuration = 27500; // Calibrated 11/21/22
const long closingDurationA = 29000; // Calibrated 11/21/22
const long closingDurationB = 30000; // Calibrated 11/21/22

String FurnaceAState="Closed", FurnaceBState="Closed";
String prevFurnaceAState="Closed", prevFurnaceBState="Closed";

void endFurnaceRoutine() {
  digitalWrite(in1, HIGH);
  digitalWrite(in2, HIGH);
  digitalWrite(enA, LOW);
  digitalWrite(in4, HIGH);
  digitalWrite(in3, HIGH);
  digitalWrite(enB, LOW);
}

auto runningTimer=timer.in(1000,endFurnaceRoutine);

enum State {
  RUNNING,
  STOP,
  ERR
};

State state = STOP;

String openFurnaceA(){
  Serial.print("Opening furnace A...");
  reply="Opening furnace A...";
  digitalWrite(in1, LOW);
  digitalWrite(in2, HIGH);
  state = RUNNING;
  digitalWrite(enA, HIGH);
  runningTimer = timer.in(maxOpeningADuration,emergencyStopOpeningFurnaceA);
  return reply;
}

void gracefulStopOpeningFurnaceA(){
  timer.cancel(runningTimer);
  state = STOP;
  FurnaceAState = "Open";
  endFurnaceRoutine();
  Serial.println("Furnace A opened gracefully.");
}

void emergencyStopOpeningFurnaceA(){
  state = ERR;
  timer.cancel(runningTimer);
  FurnaceAState = "Open";
//  reason = "BOX FURNACE A STOPPED DUE TO TIME PROTECTION!"; Memory Overrun, Cannot use!!
  endFurnaceRoutine();
  //Auto closing furnace for safety
  digitalWrite(in1, HIGH);
  digitalWrite(in2, LOW);
  digitalWrite(enA, HIGH);
  runningTimer = timer.in(closingDurationA,EmergencyCloseFurnaceA);
}

void EmergencyCloseFurnaceA(){
  FurnaceAState="Unknown";
  timer.cancel(runningTimer);
  state = ERR;
  endFurnaceRoutine();
  Serial.println("Furnace A emergency closed.");
}

String closeFurnaceA(){
  Serial.print("Closing furnace A...");
  reply="Closing furnace A...";
  state = RUNNING;
  digitalWrite(in1, HIGH);
  digitalWrite(in2, LOW);
  digitalWrite(enA, HIGH);
  runningTimer = timer.in(closingDurationA,gracefulStopClosingFurnaceA);
  return reply;
}

void gracefulStopClosingFurnaceA(){
  FurnaceAState="Closed";
  timer.cancel(runningTimer);
  state = STOP;
  endFurnaceRoutine();
  Serial.println("Furnace A closed gracefully.");
}

String openFurnaceB(){
  Serial.print("Opening furnace B...");
  reply="Opening furnace B...";
  digitalWrite(in4, HIGH);
  digitalWrite(in3, LOW);
  digitalWrite(enB, HIGH);
  state = RUNNING;
  runningTimer = timer.in(maxOpeningBDuration,emergencyStopOpeningFurnaceB);
  return reply;
}

void gracefulStopOpeningFurnaceB(){
  timer.cancel(runningTimer);
  state = STOP;
  FurnaceBState = "Open";
  endFurnaceRoutine();
  Serial.println("Furnace B opened gracefully.");
}

void emergencyStopOpeningFurnaceB(){
  state = ERR;
  timer.cancel(runningTimer);
  FurnaceBState = "Open";
//  reason = "BOX FURNACE B STOPPED DUE TO TIME PROTECTION!";
  endFurnaceRoutine();
  //Auto closing furnace for safety
  digitalWrite(in4, LOW);
  digitalWrite(in3, HIGH);
  digitalWrite(enB, HIGH);
  runningTimer = timer.in(closingDurationB,EmergencyCloseFurnaceB);
}

void EmergencyCloseFurnaceB(){
  FurnaceBState="Unknown";
  timer.cancel(runningTimer);
  state = ERR;
  endFurnaceRoutine();
  Serial.println("Furnace B emergency closed.");
}

String closeFurnaceB(){
  Serial.print("Closing furnace B...");
  reply="Closing furnace B...";
  state = RUNNING;
  digitalWrite(in4, LOW);
  digitalWrite(in3, HIGH);
  digitalWrite(enB, HIGH);
  runningTimer = timer.in(closingDurationB,gracefulStopClosingFurnaceB);
  return reply;
}

void gracefulStopClosingFurnaceB(){
  FurnaceBState = "Closed";
  timer.cancel(runningTimer);
  state = STOP;
  endFurnaceRoutine();
  Serial.println("Furnace B closed gracefully.");
}

String checkStatus(){
//  Serial.println(" I received the command Status");
  reply="State: ";
  if (state == ERR) {
//    Serial.println(reason);
    reply=reply+"ERROR; ";
  }
  else if(state == RUNNING){
    reply=reply+"RUNNING; ";
  }
  else if(state == STOP){
    reply=reply+"STOP; ";
  }
  reply=reply+"Furnace A: "+FurnaceAState+"; "+"Furnace B: "+FurnaceBState+";";
  Serial.println(reply);
  return reply;
}

COROUTINE(checkLS_coroutine) {
  COROUTINE_LOOP() {
    COROUTINE_DELAY(30);
    if(digitalRead(dlsA) == 1){
      Serial.println("Furnace A is HIGH");
      if(command=="Open A" and state!=ERR){
        gracefulStopOpeningFurnaceA();
        }
    }
    if(digitalRead(dlsB) == 1){
      Serial.println("Furnace B is HIGH");
      if(command=="Open B" and state!=ERR){
        gracefulStopOpeningFurnaceB();
      }
    }
  }
}

COROUTINE(main_coroutine) {
  COROUTINE_LOOP() {
    COROUTINE_DELAY(30);
    // listen for incoming clients
    EthernetClient client = server.available();
    if (client) {
      Serial.println("Client connected.");
      while (client.connected()) {
        if (client.available()) {
          char c = client.read();
          clientMsg += c; //store the received chracters in a string
          //if the character is an "end of line" the whole message is recieved
          if (c == '\n') {
            clientMsg.trim();
            Serial.println("RECEIVED>>" + clientMsg); //print it to the serial
            if (clientMsg == "Open A" and state!=ERR and state!=RUNNING) {
              if (FurnaceAState == "Closed"){
                reply=openFurnaceA();
                command="Open A";
                client.print(reply);
              }
              else if (FurnaceAState == "Open"){
                reply=checkStatus();
                client.print(reply);
              }
            }
            else if (clientMsg == "Close A" and state!=ERR and state!=RUNNING) {
              if (FurnaceAState == "Open"){
                reply=closeFurnaceA();
                command="Close A";
                client.print(reply);
              }
              else if (FurnaceAState == "Closed"){
                reply=checkStatus();
                client.print(reply);
              }
            }
            else if (clientMsg == "Open B" and state!=ERR and state!=RUNNING) {
              if (FurnaceBState == "Closed"){
                reply=openFurnaceB();
                command="Open B";
                client.print(reply);
              }
              else if (FurnaceBState == "Open"){
                reply=checkStatus();
                client.print(reply);
              }
            }
            else if (clientMsg == "Close B" and state!=ERR and state!=RUNNING) {
              if (FurnaceBState == "Open"){
                reply=closeFurnaceB();
                command="Close B";
                client.print(reply);
              }
              else if (FurnaceBState == "Closed"){
                reply=checkStatus();
                client.print(reply);
              }
            }
            else if ((clientMsg == "Open A" or clientMsg == "Open B" or clientMsg == "Close A" or clientMsg == "Close B") and (state==ERR or state==RUNNING)){
              reply=checkStatus();
              client.print(reply);
            }
            else if (clientMsg == "Status") {
              reply=checkStatus();
              client.print(reply);
            }
            else{
              Serial.println("Wrong command");
              client.print("Wrong command");
            }
            clientMsg = "";
            reply="";
          }
        }
      }
      // give the Client time to receive the data
      delay(10);
      // close the connection:
      client.stop();
      Serial.println(("Client disconnected."));
    }
  }
}

void setup()
{
  timer.cancel(runningTimer);
  Serial.end(); //restarting serial communication with every setup
  Serial.begin(9600);
  pinMode(enA, OUTPUT);
  pinMode(enB, OUTPUT);
  pinMode(dlsA, INPUT_PULLUP);
  pinMode(dlsB, INPUT_PULLUP);
  pinMode(in1, OUTPUT);
  pinMode(in2, OUTPUT);
  pinMode(in4, OUTPUT);
  pinMode(in3, OUTPUT);
  digitalWrite(in1, HIGH);
  digitalWrite(in2, HIGH);
  digitalWrite(enA, LOW);
  digitalWrite(in4, HIGH);
  digitalWrite(in3, HIGH);
  digitalWrite(enB, LOW);
  //Initialize the LED as an output
  //digitalWrite(LED_BUILTIN, LOW);
  // turn the LED off by making the voltage LOW
  // start the serial for debugging
  while (!Serial) {
    delay(1000);
    if (serialwait == serialwaitingtime) {
      break;
    }
    serialwait++;
  }
  serialwait = 0;
  Serial.println(("Serial started. Now starting ethernet"));
  // start the Ethernet connection and the server:
  if (Ethernet.begin(mac) == 0) {
    Serial.println("Failed to configure Ethernet using DHCP");
    while (true) {
      delay(1000);
    }
  }
  server.begin();
  Serial.print(("Ethernet/server started started at "));
  Serial.print(Ethernet.localIP());
  Serial.print((" : "));
  Serial.print(serverPort);
  Serial.print((" and gateway "));
  Serial.print(Ethernet.gatewayIP());
  Serial.println((" ."));
  // Check for Ethernet hardware present
  if (Ethernet.hardwareStatus() == EthernetNoHardware) {
    Serial.println(("Ethernet shield was not found. The code does nothing from now on."));
    while (true) {
      delay(1000); // do nothing, no point running without Ethernet hardware
    }
  }
  if (Ethernet.linkStatus() == LinkOFF) {
    while ((Ethernet.linkStatus() == LinkOFF)) {
      Serial.println(("Ethernet cable is not connected. Trying again in 2 seconds."));
      delay(2000);
    }
    Serial.println(("Ethernet cable is now detected. Resuming the routine now..."));
  }
  Serial.println(("Please write either Open A, Close A, Open B, Close B, or Status."));
  Serial.println(("Write debug or deployment to set mode"));
}

void loop()
{
  timer.tick();
  main_coroutine.runCoroutine();
  checkLS_coroutine.runCoroutine();
}
