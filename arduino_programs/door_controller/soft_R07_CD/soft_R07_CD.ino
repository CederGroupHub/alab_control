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
int lsC=0;
int lsD=0;

int serialwait = 0;
int serialwaitingtime = 6;
byte mac[] = { 0x00, 0x52, 0x16, 0x64, 0xC0, 0x11 };
//00:52:16:64:C0:39

int serverPort = 8888;

// Initialize the Ethernet server library
// with the IP address and port you want to use
EthernetServer server(serverPort);
EthernetClient client;

// Furnace closing time
#define serialwaitingtime 5 //time in seconds to wait for the serial connection to be stablished, or it will be canceled.

// Motor C ; Furnace C

#define enC 2 //enable motor C
#define in2 3
#define in1 A0
#define dlsC 5 //door limit switch for box furnace C

// Motor D ; Furnace D

#define enD 6 //enable motor D
#define in4 7
#define in3 8
#define dlsD 9 //door limit switch for box furnace D

//pins 4, 10, 11, 12, 13 are reserved for the ethernet shield

unsigned long currentTime,previousTime,duration;
const long maxOpeningCDuration = 21000; // 
const long maxOpeningDDuration = 21000; // 
const long closingDurationC = 25000; //
const long closingDurationD = 25000; //

String FurnaceCState="Closed", FurnaceDState="Closed";
String prevFurnaceCState="Closed", prevFurnaceDState="Closed";

void endFurnaceRoutine() {
  digitalWrite(in1, HIGH);
  digitalWrite(in2, HIGH);
  digitalWrite(enC, LOW);
  digitalWrite(in4, HIGH);
  digitalWrite(in3, HIGH);
  digitalWrite(enD, LOW);
}

auto runningTimer=timer.in(1000,endFurnaceRoutine);

enum State {
  RUNNING,
  STOP,
  ERR
};

State state = STOP;

String openFurnaceC(){
  Serial.print("Opening furnace C...");
  reply="Opening furnace C...";
  digitalWrite(in1, LOW);
  digitalWrite(in2, HIGH);
  state = RUNNING;
  digitalWrite(enC, HIGH);
  runningTimer = timer.in(maxOpeningCDuration,emergencyStopOpeningFurnaceC);
  return reply;
}

void gracefulStopOpeningFurnaceC(){
  timer.cancel(runningTimer);
  state = STOP;
  FurnaceCState = "Open";
  endFurnaceRoutine();
  Serial.println("Furnace C opened gracefully.");
}

void emergencyStopOpeningFurnaceC(){
  state = ERR;
  timer.cancel(runningTimer);
  FurnaceCState = "Open";
//  reason = "BOX FURNACE C STOPPED DUE TO TIME PROTECTION!"; Memory Overrun, Cannot use!!
  endFurnaceRoutine();
  //Auto closing furnace for safety
  digitalWrite(in1, HIGH);
  digitalWrite(in2, LOW);
  digitalWrite(enC, HIGH);
  runningTimer = timer.in(closingDurationC,EmergencyCloseFurnaceC);
}

void EmergencyCloseFurnaceC(){
  FurnaceCState="Unknown";
  timer.cancel(runningTimer);
  state = ERR;
  endFurnaceRoutine();
  Serial.println("Furnace C emergency closed.");
}

String closeFurnaceC(){
  Serial.print("Closing furnace C...");
  reply="Closing furnace C...";
  state = RUNNING;
  digitalWrite(in1, HIGH);
  digitalWrite(in2, LOW);
  digitalWrite(enC, HIGH);
  runningTimer = timer.in(closingDurationC,gracefulStopClosingFurnaceC);
  return reply;
}

void gracefulStopClosingFurnaceC(){
  FurnaceCState="Closed";
  timer.cancel(runningTimer);
  state = STOP;
  endFurnaceRoutine();
  Serial.println("Furnace C closed gracefully.");
}

String openFurnaceD(){
  Serial.print("Opening furnace D...");
  reply="Opening furnace D...";
  digitalWrite(in4, HIGH);
  digitalWrite(in3, LOW);
  state = RUNNING;
  digitalWrite(enD, HIGH);
  runningTimer = timer.in(maxOpeningDDuration,emergencyStopOpeningFurnaceD);
  return reply;
}

void gracefulStopOpeningFurnaceD(){
  timer.cancel(runningTimer);
  state = STOP;
  FurnaceDState = "Open";
  endFurnaceRoutine();
  Serial.println("Furnace D opened gracefully.");
}

void emergencyStopOpeningFurnaceD(){
  state = ERR;
  timer.cancel(runningTimer);
  FurnaceDState = "Open";
//  reason = "BOX FURNACE D STOPPED DUE TO TIME PROTECTION!"; Cannot use, Memory Overrun!
  endFurnaceRoutine();
  //Auto closing furnace for safety
  digitalWrite(in4, LOW);
  digitalWrite(in3, HIGH);
  digitalWrite(enD, HIGH);
  runningTimer = timer.in(closingDurationD,EmergencyCloseFurnaceD);
}

void EmergencyCloseFurnaceD(){
  FurnaceDState="Unknown";
  timer.cancel(runningTimer);
  state = ERR;
  endFurnaceRoutine();
  Serial.println("Furnace D emergency closed.");
}

String closeFurnaceD(){
  Serial.print("Closing furnace D...");
  reply="Closing furnace D...";
  state = RUNNING;
  digitalWrite(in4, LOW);
  digitalWrite(in3, HIGH);
  digitalWrite(enD, HIGH);
  runningTimer = timer.in(closingDurationD,gracefulStopClosingFurnaceD);
  return reply;
}

void gracefulStopClosingFurnaceD(){
  FurnaceDState = "Closed";
  timer.cancel(runningTimer);
  state = STOP;
  endFurnaceRoutine();
  Serial.println("Furnace D closed gracefully.");
}

String checkStatus(){
  Serial.println(" I received the command Status");
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
  reply=reply+"Furnace C: "+FurnaceCState+"; "+"Furnace D: "+FurnaceDState+";";
  Serial.println(reply);
  return reply;
}

COROUTINE(checkLS_coroutine) {
  COROUTINE_LOOP() {
    COROUTINE_DELAY(30);
    if(digitalRead(dlsC) == 1){
    Serial.println("Furnace C is HIGH");
    if(command=="Open C" and state!=ERR){
      gracefulStopOpeningFurnaceC();
      }
    }
    if(digitalRead(dlsD) == 1){
      Serial.println("Furnace D is HIGH");
      if(command=="Open D" and state!=ERR){
        gracefulStopOpeningFurnaceD();
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
            if (clientMsg == "Open C" and state!=ERR and state!=RUNNING) {
              if (FurnaceCState == "Closed"){
                reply=openFurnaceC();
                command="Open C";
                client.print(reply);
              }
              else if (FurnaceCState == "Open"){
                reply=checkStatus();
                client.print(reply);
              }
            }
            else if (clientMsg == "Close C" and state!=ERR and state!=RUNNING) {
              if (FurnaceCState == "Open"){
                reply=closeFurnaceC();
                command="Close C";
                client.print(reply);
              }
              else if (FurnaceCState == "Closed"){
                reply=checkStatus();
                client.print(reply);
              }
            }
            else if (clientMsg == "Open D" and state!=ERR and state!=RUNNING) {
              if (FurnaceDState == "Closed"){
                reply=openFurnaceD();
                command="Open D";
                client.print(reply);
              }
              else if (FurnaceDState == "Open"){
                reply=checkStatus();
                client.print(reply);
              }
            }
            else if (clientMsg == "Close D" and state!=ERR and state!=RUNNING) {
              if (FurnaceDState == "Open"){
                reply=closeFurnaceD();
                command="Close D";
                client.print(reply);
              }
              else if (FurnaceDState == "Closed"){
                reply=checkStatus();
                client.print(reply);
              }
            }
            else if ((clientMsg == "Open C" or clientMsg == "Open D" or clientMsg == "Close C" or clientMsg == "Close D") and (state==ERR or state==RUNNING)){
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
  pinMode(enC, OUTPUT);
  pinMode(enD, OUTPUT);
  pinMode(dlsC, INPUT_PULLUP);
  pinMode(dlsD, INPUT_PULLUP);
  pinMode(in1, OUTPUT);
  pinMode(in2, OUTPUT);
  pinMode(in4, OUTPUT);
  pinMode(in3, OUTPUT);
  digitalWrite(in1, HIGH);
  digitalWrite(in2, HIGH);
  digitalWrite(enC, LOW);
  digitalWrite(in4, HIGH);
  digitalWrite(in3, HIGH);
  digitalWrite(enD, LOW);
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
  Serial.println(("Please write either Open C, Close C, Open D, Close D, or Status."));
  Serial.println(("Write debug or deployment to set mode"));
}

void loop()
{
  timer.tick();
  main_coroutine.runCoroutine();
  checkLS_coroutine.runCoroutine();
}
