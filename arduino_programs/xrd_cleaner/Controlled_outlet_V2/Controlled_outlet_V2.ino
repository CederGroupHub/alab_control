#include <SPI.h>
#include <Ethernet.h>
#include<ArduinoJson.h>
#include <AceRoutine.h>

String clientMsg = "";
String command = "";
String reply="";
//pins 4, 10, 11, 12, 13 are reserved for the ethernet shield
int serialwait = 0;
int serialwaitingtime = 6;
byte mac[] = { 0xDE, 0xAD, 0xBE, 0xEF, 0xFE, 0x78 };
IPAddress serverIP(192,168,0,43);
int serverPort = 8888;
// Initialize the Ethernet server library
// with the IP address and port you want to use
EthernetServer server(serverPort);
EthernetClient client;

//#define output1 8 For reset only (NOT IMPLEMENTED YET IN THE HARDWARE)
#define output2 9

unsigned long resetTime, resetTimePrev;
const long resetDuration = 5000;
unsigned long vacuumTime,vacuumTimePrev;
const long maxVacuumDuration = 30000;
String equipmentAState = "On";
String equipmentBState = "Off";
bool reset_done = true;

enum State {
  RUNNING,
  STOP,
  ERR
};

State state = STOP;

String checkStatus(){
  reply="State: ";
  if (state == ERR) {
    reply=reply+"ERROR; ";
  }
  else if(state == RUNNING){
    reply=reply+"RUNNING; ";
  }
  else if(state == STOP){
    reply=reply+"STOP; ";
  }
  reply=reply+"Equipment A: "+equipmentAState+"; "+"Equipment B: "+equipmentBState+";";
  Serial.println(reply);
  return reply;
}

void turnOff() {
//  digitalWrite(output1, LOW); For reset only (NOT IMPLEMENTED YET IN THE HARDWARE)
  digitalWrite(output2, LOW);
}

String resetEquipmentA(){
  reply="Equipment A >> RESET";
  Serial.println("Equipment A >> RESET (5 seconds)...");
//  digitalWrite(output1, HIGH); For reset only (NOT IMPLEMENTED YET IN THE HARDWARE)
  reset_done=false;
  equipmentAState="Resetting";
  state=RUNNING;
  resetTime = millis();
  resetTimePrev = millis();
  return reply;
}

String turnOnEquipmentB(){
  reply="Equipment B >> ON";
  Serial.println("Equipment B >> ON");
  digitalWrite(output2, HIGH);
  equipmentBState="On";
  vacuumTime = millis();
  vacuumTimePrev = millis();
  return reply;
}

String turnOffEquipmentB(){
  reply="Equipment B >> OFF";
  Serial.println("Equipment B >> OFF");
  digitalWrite(output2, LOW);
  equipmentBState="Off";
  command="";
  state=STOP;
  return reply;
}

COROUTINE(main_coroutine) {
  COROUTINE_LOOP() {
    COROUTINE_DELAY(10);
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
            if (clientMsg == "Reset Equipment A" and state!=ERR and state!=RUNNING) {
              reply=resetEquipmentA();
              command="Reset A";
              client.print(reply);
            }
            else if (clientMsg == "Turn on Equipment B" and state!=ERR and state!=RUNNING) {
              if (equipmentBState == "Off"){
                reply=turnOnEquipmentB();
                command="Turn on B";
                client.print(reply);
              }
              else if (equipmentBState == "On"){
                reply=checkStatus();
                client.print(reply);
              }
            }
            else if (clientMsg == "Turn off Equipment B" and state!=ERR and state!=RUNNING) {
              if (equipmentBState == "On"){
                reply=turnOffEquipmentB();
                command="Turn off B";
                client.print(reply);
              }
              else if (equipmentBState == "Off"){
                reply=checkStatus();
                client.print(reply);
              }
            }
            else if ((clientMsg == "Reset Equipment A" or clientMsg == "Turn on Equipment B" or clientMsg == "Turn off Equipment B") and (state==ERR or state==RUNNING)){
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
      // close the connection:
      client.stop();
      Serial.println(("Client disconnected."));
    }
  }
}

COROUTINE(reset_coroutine) {
  COROUTINE_LOOP() {
    COROUTINE_DELAY(30);
    if (command=="Reset A" and reset_done==false){
      resetTime = millis();
      if ((resetTime-resetTimePrev)>resetDuration){
        equipmentAState="On";
        Serial.println("Equipment A >> RESET DONE");
//        digitalWrite(output1, LOW); For reset only (NOT IMPLEMENTED YET IN THE HARDWARE)
        reset_done=true;
        state=STOP;
        command="";
      }
    }
  }
}

COROUTINE(vacuum_coroutine) {
  COROUTINE_LOOP() {
    COROUTINE_DELAY(30);
    if (command=="Turn on B"){
      vacuumTime = millis();
      if ((vacuumTime-vacuumTimePrev)>maxVacuumDuration){
        equipmentBState="Off";
        Serial.println("Equipment B >> Emergency Turn off");
        digitalWrite(output2, LOW);
        state=ERR;
        command="";
      }
    }
  }
}

void setup()
{
  Serial.end(); //restarting serial communication with every setup
  Serial.begin(9600);
//  pinMode(output1, OUTPUT);For reset only (NOT IMPLEMENTED YET IN THE HARDWARE)
  pinMode(output2, OUTPUT);
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
  Ethernet.begin(mac, serverIP);
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
  resetTime = millis();
  resetTimePrev = millis();
  vacuumTime = millis();
  vacuumTimePrev = millis();
}

void loop()
{
  main_coroutine.runCoroutine();
  reset_coroutine.runCoroutine();
  vacuum_coroutine.runCoroutine();
}
