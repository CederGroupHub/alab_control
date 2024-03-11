#include <SPI.h>
#include <Ethernet.h>
#include<ArduinoJson.h>
#include <AceRoutine.h>

String clientMsg = "";
String command = "";
String reply = "";
//pins 4, 10, 11, 12, 13 are reserved for the ethernet shield
int serialWait = 0;
int serialWaitingTime = 6;
byte mac[] = { 0xDE, 0xAD, 0xBE, 0xEF, 0xFE, 0x78 };
IPAddress serverIP(192,168,0,43);
int serverPort = 8888;
// Initialize the Ethernet server library
// with the IP address and port you want to use
EthernetServer server(serverPort);
EthernetClient client;

// I changed the equipment A and equipment B definition to vacuum cleaner and reset printer because it does totally different things.
// It will confuse the reader if we say "Equipment A" and "Equipment B" but they are not identical operation wise.
#define vacuumOutput 3 // to turn on/off vacuum cleaner | HIGH = turn on vacuum, LOW = turn off vacuum
#define printerOutput 5 // to turn off/on printer  | HIGH = turn off printer, LOW = turn on printer

unsigned long vacuumTime,vacuumTimePrev;
const long maxVacuumDuration = 30000;
unsigned long resetTime, resetTimePrev;
const long resetDuration = 10000;
String vacuumState = "Off";
String printerState = "On";
bool resetDone = true;

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
  reply=reply+"Vacuum: "+vacuumState+"; "+"3D Printer: "+printerState+";";
  Serial.println(reply);
  return reply;
}

String resetPrinter(){
  reply="3D Printer >> RESET";
  Serial.println(F("3D Printer >> RESET"));
  digitalWrite(printerOutput, HIGH);
  resetDone=false;
  printerState="Off";
  state=RUNNING;
  resetTime = millis();
  resetTimePrev = millis();
  return reply;
}

String turnOnVacuum(){
  reply="Vacuum Cleaner >> ON";
  Serial.println("Vacuum Cleaner >> ON");
  digitalWrite(vacuumOutput, HIGH);
  vacuumState = "On";
  vacuumTime = millis();
  vacuumTimePrev = millis();
  return reply;
}

String turnOffVacuum(){
  reply="Vacuum Cleaner >> OFF";
  Serial.println("Vacuum Cleaner >> OFF");
  digitalWrite(vacuumOutput, LOW);
  vacuumState="Off";
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
          clientMsg += c;
          if (c == '\n') {
            clientMsg.trim();
            Serial.println("RECEIVED>>" + clientMsg); //print it to the serial
            if (clientMsg == "Reset_Printer" and state!=ERR and state!=RUNNING) {
              reply=resetPrinter();
              command="Reset_Printer";
              client.print(reply);
            }
            else if (clientMsg == "Turn_On_Vacuum" and state!=ERR and state!=RUNNING) {
              if (vacuumState == "Off"){
                reply=turnOnVacuum();
                command="Turn_On_Vacuum";
                client.print(reply);
              }
              else if (vacuumState == "On"){
                reply=checkStatus();
                client.print(reply);
              }
            }
            else if (clientMsg == "Turn_Off_Vacuum" and state!=ERR and state!=RUNNING) {
              if (vacuumState == "On"){
                reply=turnOffVacuum();
                command="Turn_Off_Vacuum";
                client.print(reply);
              }
              else if (vacuumState == "Off"){
                reply=checkStatus();
                client.print(reply);
              }
            }
            // Return status as default and not run anything if it is still RUNNING or in ERROR state
            else if ((clientMsg == "Status") or ((clientMsg == "Reset_Printer" or clientMsg == "Turn_On_Vacuum" or clientMsg == "Turn_Off_Vacuum") and (state==ERR or state==RUNNING))){
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
    if (command=="Reset_Printer" and resetDone==false){
      resetTime = millis();
      if ((resetTime-resetTimePrev)>resetDuration){
        printerState="On";
        Serial.println("3D Printer >> RESET DONE");
        digitalWrite(printerOutput, LOW);
        resetDone=true;
        state=STOP;
        command="";
      }
    }
  }
}

COROUTINE(vacuum_coroutine) {
  COROUTINE_LOOP() {
    COROUTINE_DELAY(30);
    if (command=="Turn_On_Vacuum"){
      vacuumTime = millis();
      if ((vacuumTime-vacuumTimePrev)>maxVacuumDuration){
        vacuumState="Off";
        Serial.println("Vacuum Cleaner >> Emergency Turn off");
        digitalWrite(vacuumOutput, LOW);
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
  pinMode(vacuumOutput, OUTPUT);
  pinMode(printerOutput, OUTPUT);
  while (!Serial) {
    delay(1000);
    if (serialWait == serialWaitingTime) {
      break;
    }
    serialWait++;
  }
  serialWait = 0;
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
